"""Verifier: deterministic grounding + NLI entailment, max 3 attempts/claim.

Two-stage check per claim:
1. Grounding (no LLM): the quote must appear verbatim in the cited doc text.
   Fabricated quotes are dropped here, deterministically, costing nothing.
2. Entailment (fast model): does the quote actually support the claim?

Unsupported claims get a strict re-extract against the same evidence
(up to MAX_ATTEMPTS total rounds), then are dropped. Design note: the retry
loop lives inside `verify_claims` rather than as a LangGraph conditional
edge — same bound, same drop semantics, but one node, sequential state
writes, and far simpler tests.
"""

import asyncio

from agents.llm import LLMClient
from tools.scrape import normalize

MAX_ATTEMPTS = 3

NLI_SYSTEM = """You judge whether a quote supports a claim.
Return JSON only: {"verdict": "supported|unsupported", "reason": "short"}
Rules:
- supported: the quote directly states or clearly entails the claim.
- unsupported: the quote is off-topic, contradicts, or is too vague to back the claim.
- Judge only what is written. No outside knowledge."""

REEXTRACT_SYSTEM = """A claim was judged unsupported by its quote. Fix it or drop it.
You get the original claim, the rejected quote, and the source excerpt.
Return JSON only, one of:
{"text": "corrected claim strictly supported by the excerpt", "quote": "verbatim quote from the excerpt, max 40 words"}
{} — if nothing in the excerpt supports any version of the claim.
Rules: the quote must be copied verbatim from the excerpt."""


def grounding_ok(quote: str, doc_text: str) -> bool:
    q = normalize(quote)
    return len(q) >= 10 and q in normalize(doc_text)


async def nli_check(claim_text: str, quote: str, client: LLMClient) -> tuple[bool, str]:
    try:
        data = await client.acomplete_json(
            system=NLI_SYSTEM,
            user=f"Claim: {claim_text}\nQuote: {quote}\nReturn JSON only.",
        )
        verdict = str(data.get("verdict", "unsupported")).strip().lower()
        return verdict == "supported", str(data.get("reason", ""))[:200]
    except Exception as e:
        return False, f"nli_error:{type(e).__name__}"


async def strict_reextract(
    claim_text: str, rejected_quote: str, doc_text: str, client: LLMClient
) -> dict | None:
    try:
        data = await client.acomplete_json(
            system=REEXTRACT_SYSTEM,
            user=(
                f"Claim: {claim_text}\nRejected quote: {rejected_quote}\n"
                f"Excerpt:\n{doc_text[:2000]}\nReturn JSON only."
            ),
        )
        text, quote = str(data.get("text", "")).strip(), str(data.get("quote", "")).strip()
        if text and quote and normalize(quote) in normalize(doc_text):
            return {"text": text, "quote": quote}
        return None
    except Exception:
        return None


async def verify_claims(
    claims: list[dict],
    evidence: dict[str, str],
    client: LLMClient,
    *,
    limit: int = 4,
) -> list[dict]:
    """Settle every claim to supported/unsupported. Never raises."""
    sem = asyncio.Semaphore(limit)

    async def settle(claim: dict) -> dict:
        settled = dict(claim)
        settled.setdefault("attempts", 0)
        url = settled.get("url", "")
        doc_text = evidence.get(url, "")
        try:
            async with sem:
                while settled["attempts"] < MAX_ATTEMPTS:
                    settled["attempts"] += 1
                    if not grounding_ok(settled.get("quote", ""), doc_text):
                        settled.update(verdict="unsupported", reason="quote_not_in_source")
                        break
                    ok, reason = await nli_check(
                        settled.get("text", ""), settled.get("quote", ""), client
                    )
                    if ok:
                        settled.update(verdict="supported", reason=reason)
                        break
                    if settled["attempts"] >= MAX_ATTEMPTS:
                        settled.update(verdict="unsupported", reason=reason)
                        break
                    fixed = await strict_reextract(
                        settled.get("text", ""),
                        settled.get("quote", ""),
                        doc_text,
                        client,
                    )
                    if fixed is None:
                        settled.update(verdict="unsupported", reason="reextract_empty")
                        break
                    settled.update(fixed)  # next round re-verifies the fix
        except Exception as e:
            settled.update(verdict="unsupported", reason=f"error:{type(e).__name__}")
        return settled

    return await asyncio.gather(*(settle(c) for c in claims))
