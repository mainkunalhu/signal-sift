"""Researcher: search -> scrape -> extract claims. One instance per query run.

`Researcher` holds injectable collaborators plus a semaphore shared across
the run's parallel `Send` branches, so free-tier Groq/network budgets are
never exceeded no matter how wide the planner fans out.

Test doubles (fake search/scrape/extractor) keep the whole pipeline offline
in unit tests; production wires real tools in `routes/research.py`.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from agents.llm import LLMClient
from tools.dedup import dedupe_docs
from tools.embed import EmbedFn
from tools.scrape import Doc, scrape_many
from tools.search import SearchHit, web_search

EXTRACT_SYSTEM = """You are SignalSift's evidence extractor. Given a sub-question and
numbered source excerpts, pull out atomic factual claims.
Return JSON only, exactly this shape:
{"claims": [{"text": "atomic factual claim", "quote": "verbatim supporting quote, max 40 words", "url": "source url"}]}
Rules:
- Max 8 claims, most important first.
- Every claim needs a verbatim quote copied from the excerpts.
- url must be one of the provided source urls, exactly as given.
- No claim without evidence. Drop anything unsupported. Dedupe repeats."""

SearchFn = Callable[..., Awaitable[tuple[list[SearchHit], object]]]
ScrapeFn = Callable[..., Awaitable[tuple[list[Doc], object]]]


class ResearcherLike(Protocol):
    """Structural seam: anything with `run(sub_question) -> dict` plugs into the graph."""

    async def run(self, sub_question: dict) -> dict: ...


class Researcher:
    def __init__(
        self,
        *,
        extractor: LLMClient,
        limit: int = 4,
        top_k: int = 5,
        top_docs: int = 3,
        search_fn: SearchFn = web_search,
        scrape_fn: ScrapeFn = scrape_many,
        embed_fn: EmbedFn | None = None,
    ) -> None:
        self._extractor = extractor
        self._sem = asyncio.Semaphore(limit)
        self._top_k = top_k
        self._top_docs = top_docs
        self._search_fn = search_fn
        self._scrape_fn = scrape_fn
        self._embed_fn = embed_fn

    async def run(self, sub_question: dict) -> dict:
        """Full pipeline for one sub-question. Never raises — degrades to empty."""
        async with self._sem:
            t0 = time.perf_counter()
            sq_id = sub_question.get("id", "sq-00")
            question = sub_question.get("question", "")
            queries = [q for q in sub_question.get("search_queries", []) if q] or [question]
            try:
                t_search = time.perf_counter()
                hits, _ = await self._search_fn(queries, top_k=self._top_k)
                search_s = round(time.perf_counter() - t_search, 3)
                t_scrape = time.perf_counter()
                # Scrape only what we keep: bounding inputs bounds the tail.
                docs, _ = await self._scrape_fn(hits[: self._top_docs * 2])
                docs = await self._near_dedupe(docs)
                docs = docs[: self._top_docs]
                scrape_s = round(time.perf_counter() - t_scrape, 3)
                t_extract = time.perf_counter()
                claims = await self._extract(question, docs) if docs else []
                extract_s = round(time.perf_counter() - t_extract, 3)
            except Exception:
                docs, claims = [], []
                search_s = scrape_s = extract_s = 0.0
            return {
                "sub_question_id": sq_id,
                "question": question,
                "search_queries": queries,
                "snippets": [
                    {
                        "url": d.url,
                        "title": d.title,
                        "text": d.text[:500],
                        **({"merged_urls": d.merged_urls} if d.merged_urls else {}),
                    }
                    for d in docs
                ],
                "evidence": {d.url: d.text[:2000] for d in docs},
                "claims": claims,
                "stats": {
                    "docs": len(docs),
                    "claims": len(claims),
                    "seconds": round(time.perf_counter() - t0, 3),
                    "search_s": search_s,
                    "scrape_s": scrape_s,
                    "extract_s": extract_s,
                },
            }

    async def _near_dedupe(self, docs: list[Doc]) -> list[Doc]:
        """Drop near-duplicate bodies (cosine > 0.92), merging urls into winners.

        Skipped when no `embed_fn` is wired (tests stay offline and fast).
        """
        if self._embed_fn is None or len(docs) < 2:
            return docs
        try:
            vectors = await self._embed_fn([d.text[:1000] for d in docs])
            out = dedupe_docs(
                [
                    {
                        "url": d.url,
                        "title": d.title,
                        "text": d.text,
                        "content_hash": d.content_hash,
                    }
                    for d in docs
                ],
                vectors,
            )
            by_url = {d.url: d for d in docs}
            merged: list[Doc] = []
            for survivor in out["docs"]:
                doc = by_url[survivor["url"]]
                doc.merged_urls = survivor.get("merged_urls", [])
                merged.append(doc)
            return merged
        except Exception:
            return docs

    async def _extract(self, question: str, docs: list[Doc]) -> list[dict]:
        evidence = "\n\n".join(
            f"[{i + 1}] {d.title} ({d.url})\n{d.text[:1500]}" for i, d in enumerate(docs)
        )
        try:
            data = await self._extractor.acomplete_json(
                system=EXTRACT_SYSTEM,
                user=f"Sub-question: {question}\n\nSources:\n{evidence}\n\nReturn JSON only.",
            )
        except Exception:
            return []
        allowed = {d.url for d in docs}
        claims: list[dict] = []
        for raw in (data.get("claims", []) or [])[:8]:
            if not isinstance(raw, dict):
                continue
            text, quote, url = (
                str(raw.get("text", "")).strip(),
                str(raw.get("quote", "")).strip(),
                str(raw.get("url", "")).strip(),
            )
            if text and quote and url in allowed:
                claims.append({"text": text, "quote": quote, "url": url})
        return claims
