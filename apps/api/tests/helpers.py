"""Offline test doubles mirroring prod seams. Never imported by prod code."""

import asyncio


class StubResearcher:
    """Topology/timing stand-in with the same `run()` contract as `Researcher`.

    Pass `claims` (list of {text, quote, url}) and `evidence` ({url: text})
    to exercise the verify/finalize stages offline.
    """

    def __init__(
        self,
        *,
        delay: float = 0.0,
        claims: list[dict] | None = None,
        evidence: dict[str, str] | None = None,
    ) -> None:
        self._delay = delay
        self._claims = claims or []
        self._evidence = evidence or {}

    async def run(self, sub_question: dict) -> dict:
        if self._delay:
            await asyncio.sleep(self._delay)
        sq_id = sub_question.get("id", "sq-00")
        queries = sub_question.get("search_queries", []) or [sub_question.get("question", "")]
        return {
            "sub_question_id": sq_id,
            "question": sub_question.get("question", ""),
            "search_queries": queries,
            "snippets": [
                {
                    "url": f"https://example.com/{sq_id}/{i}",
                    "title": f"stub source {i} for {sq_id}",
                    "text": "Offline stub — real search runs via Researcher.",
                }
                for i in (1, 2)
            ],
            "evidence": dict(self._evidence),
            "claims": [dict(c) for c in self._claims],
            "stats": {"docs": 2, "claims": len(self._claims), "seconds": self._delay},
        }
