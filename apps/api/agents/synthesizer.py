"""Synthesizer: verified claims -> cited markdown report, streamed.

Streaming + honesty: the draft streams token-by-token (live UX), then a
citation post-check runs over the assembled text. If any paragraph lacks a
valid citation, ONE repair pass rewrites the report; the canonical
`report_md` ships in `done` so the UI always converges on the checked
version, even if the live tokens were the pre-repair draft.
"""

import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from agents.llm import LLMClient

MAX_CLAIMS = 15
MAX_DOCS = 15
CITE_RE = re.compile(r"\[(\d+)\]")

SYSTEM = """You are SignalSift's report writer. Write a concise research report in
markdown from the verified claims and numbered sources below.
Rules:
- Structure: ## Summary, ## Key findings, ## Caveats (only if contested notes exist).
- When there are no contested notes, OMIT the Caveats section entirely — never
  write a placeholder like "no caveats" (it is not a factual claim and needs no citation).
- Every factual sentence ends with numeric citations like [1] or [2][3] matching SOURCES.
- Use ONLY the given sources. Citation numbers must be between 1 and {n_docs}.
- Headings need no citations. No uncited factual claims. No Sources section (appended automatically).
- Hedge contested claims explicitly ("Sources disagree...").
- Keep it tight: 300-600 words."""

REPAIR_SYSTEM = """You fix citation gaps in a research report. You get the draft, the
paragraphs missing valid citations, and the valid citation range.
Return the FULL corrected report: same markdown, same facts, citations added.
Do not invent sources. Reply with the report only."""


@dataclass
class SynthesisResult:
    report_md: str
    repaired: bool
    coverage: float
    claims_used: int
    docs_used: int
    tokens_est: int
    seconds: float


def check_citations(report_md: str, n_docs: int) -> dict:
    """Every content paragraph must carry at least one in-range citation."""
    uncited: list[str] = []
    total = 0
    for line in report_md.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or set(stripped) <= set("-=*_| :"):
            continue
        total += 1
        body = re.sub(r"^[-*>\d.)\]]+\s*", "", stripped)
        nums = [int(n) for n in CITE_RE.findall(body)]
        if not nums or any(n < 1 or n > n_docs for n in nums):
            uncited.append(stripped)
    return {
        "coverage": (total - len(uncited)) / total if total else 1.0,
        "uncited": uncited,
    }


OnToken = Callable[[str], Awaitable[None]]


class Synthesizer:
    def __init__(
        self,
        *,
        client: LLMClient,
        max_claims: int = MAX_CLAIMS,
        max_docs: int = MAX_DOCS,
        max_repairs: int = 1,
    ) -> None:
        self._client = client
        self._max_claims = max_claims
        self._max_docs = max_docs
        self._max_repairs = max_repairs

    async def run(
        self,
        claims: list[dict],
        docs: list[dict],
        *,
        on_token: OnToken | None = None,
    ) -> SynthesisResult:
        """Stream the draft (via `on_token`), then check + optional repair."""
        t0 = time.perf_counter()
        docs = docs[: self._max_docs]
        numbers = {d["url"]: i + 1 for i, d in enumerate(docs)}
        usable = [c for c in claims if any(s in numbers for s in c.get("sources", []))][
            : self._max_claims
        ]
        if not usable or not docs:
            return SynthesisResult(
                report_md="",
                repaired=False,
                coverage=0.0,
                claims_used=0,
                docs_used=len(docs),
                tokens_est=0,
                seconds=round(time.perf_counter() - t0, 3),
            )

        user = self._prompt(usable, docs, numbers)
        system = SYSTEM.format(n_docs=len(docs))
        draft_parts: list[str] = []
        async for delta in self._client.astream_text(system=system, user=user):
            draft_parts.append(delta)
            if on_token is not None:
                await on_token(delta)
        draft = "".join(draft_parts)

        report, repaired = draft, False
        best_cov = check_citations(report, len(docs))["coverage"]
        for _ in range(self._max_repairs):
            if best_cov >= 1.0:
                break
            check = check_citations(report, len(docs))
            try:
                candidate = await self._client.acomplete_text(
                    system=REPAIR_SYSTEM,
                    user=(
                        f"Draft:\n{report}\n\nParagraphs missing valid citations "
                        f"(range 1-{len(docs)}):\n"
                        + "\n".join(f"- {p[:300]}" for p in check["uncited"])
                        + "\n\nReturn the FULL corrected report."
                    ),
                )
            except Exception:
                break
            # Never regress: a repair that strips citations is discarded.
            cand_cov = check_citations(candidate, len(docs))["coverage"]
            if cand_cov > best_cov:
                report, best_cov, repaired = candidate, cand_cov, True
            else:
                break

        final_check = check_citations(report, len(docs))
        return SynthesisResult(
            report_md=report,
            repaired=repaired,
            coverage=round(final_check["coverage"], 3),
            claims_used=len(usable),
            docs_used=len(docs),
            tokens_est=len(user + report) // 4,
            seconds=round(time.perf_counter() - t0, 3),
        )

    def _prompt(self, claims: list[dict], docs: list[dict], numbers: dict[str, int]) -> str:
        sources = "\n".join(
            f"[{numbers[d['url']]}] {d.get('title', d['url'])} — {d['url']}" for d in docs
        )
        lines = []
        for claim in claims:
            nums = sorted({numbers[s] for s in claim.get("sources", []) if s in numbers})
            cites = "".join(f"[{n}]" for n in nums)
            contested = (
                " (CONTESTED: evidence disagrees — hedge this)" if claim.get("contested") else ""
            )
            lines.append(f"- Claim {cites}{contested}: {claim.get('text', '')}")
        return f"SOURCES:\n{sources}\n\nVERIFIED CLAIMS:\n" + "\n".join(lines)
