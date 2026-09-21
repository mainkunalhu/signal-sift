"""Research planner (planner model). Breaks one hard query into 5-8 sub-questions."""

from agents.llm import LLMClient
from agents.state import SubQuestion

SYSTEM = """You are SignalSift's research planner. Break the user query into atomic
sub-questions that can be investigated in parallel.
Return JSON only, exactly this shape:
{"sub_questions": [{"id": "sq-01", "question": "...", "search_queries": ["...", "..."], "priority": 1}]}
Rules:
- 5-8 sub-questions, ids sq-01, sq-02, ... in order.
- Each sub-question is self-contained (no "as above" references).
- Each has 1-3 concrete web search queries.
- priority: 1 = must-have, 2 = important, 3 = nice-to-have.
- Cover different angles; avoid overlap."""


def _coerce(payload: dict, max_subquestions: int) -> list[SubQuestion]:
    items = payload.get("sub_questions", []) if isinstance(payload, dict) else []
    valid: list[SubQuestion] = []
    for i, raw in enumerate(items):
        try:
            sq = SubQuestion(**raw) if isinstance(raw, dict) else None
            if sq is None or not sq.question.strip():
                continue
            if not sq.id:
                sq.id = f"sq-{i + 1:02d}"
            sq.search_queries = [q for q in sq.search_queries if q.strip()][:3]
            valid.append(sq)
        except Exception:
            continue
    valid.sort(key=lambda s: s.priority)
    return valid[:max_subquestions]


def _fallback(query: str) -> list[SubQuestion]:
    return [
        SubQuestion(
            id="sq-01",
            question=query,
            search_queries=[query],
            priority=1,
        )
    ]


async def plan_research(
    query: str, client: LLMClient, *, max_subquestions: int = 6
) -> list[SubQuestion]:
    """Decompose via LLM with one repair retry, then a safe single-item fallback."""
    try:
        data = await client.acomplete_json(system=SYSTEM, user=f"Query: {query}")
        valid = _coerce(data, max_subquestions)
        if len(valid) >= 2:
            return valid
        repair = await client.acomplete_json(
            system=SYSTEM + "\nYour previous JSON failed validation.",
            user=f"Query: {query}\nReturn corrected JSON only, 5-8 sub-questions.",
        )
        valid = _coerce(repair, max_subquestions)
        return valid if len(valid) >= 2 else _fallback(query)
    except Exception:
        return _fallback(query)
