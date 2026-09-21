"""Web search: SearXNG primary, Tavily fallback.

Contract: `web_search(queries, ...)` returns deduped `SearchHit`s (by URL)
across all queries. SearXNG failures (429/5xx/timeout) fall back to Tavily
when `TAVILY_API_KEY` is set; otherwise they degrade to empty results —
a researcher with zero hits returns snippets-less payloads, never raises.
"""

import asyncio
import random
from dataclasses import dataclass, field

import httpx

from config import settings


@dataclass
class SearchHit:
    url: str
    title: str = ""
    snippet: str = ""
    engine: str = ""


@dataclass
class SearchStats:
    queries: int = 0
    hits: int = 0
    fallback_used: bool = False
    errors: list[str] = field(default_factory=list)


async def _searxng_search(client: httpx.AsyncClient, query: str, *, top_k: int) -> list[SearchHit]:
    resp = await client.get(
        f"{settings.searxng_url.rstrip('/')}/search",
        params={"q": query, "format": "json", "language": "en"},
    )
    resp.raise_for_status()
    hits: list[SearchHit] = []
    for raw in (resp.json().get("results", []) or [])[:top_k]:
        url = (raw.get("url") or "").strip()
        if not url.startswith("http"):
            continue
        hits.append(
            SearchHit(
                url=url,
                title=(raw.get("title") or "")[:300],
                snippet=(raw.get("content") or "")[:500],
                engine=str(raw.get("engine", "searxng")),
            )
        )
    return hits


async def _tavily_search(client: httpx.AsyncClient, query: str, *, top_k: int) -> list[SearchHit]:
    if not settings.tavily_api_key:
        return []
    resp = await client.post(
        "https://api.tavily.com/search",
        json={
            "api_key": settings.tavily_api_key,
            "query": query,
            "max_results": top_k,
            "search_depth": "basic",
        },
    )
    resp.raise_for_status()
    return [
        SearchHit(
            url=r.get("url", ""),
            title=(r.get("title") or "")[:300],
            snippet=(r.get("content") or "")[:500],
            engine="tavily",
        )
        for r in (resp.json().get("results", []) or [])[:top_k]
        if str(r.get("url", "")).startswith("http")
    ]


async def _search_one(
    client: httpx.AsyncClient,
    query: str,
    *,
    top_k: int,
    max_retries: int,
    stats: SearchStats,
) -> list[SearchHit]:
    """One query: fast SearXNG attempt, Tavily fallback on persistent failure.

    When a Tavily key exists, SearXNG gets a single bounded attempt (no long
    retry sleeps) so a dead instance can't stall the run; otherwise SearXNG is
    retried with backoff since it's the only source.
    """
    if settings.tavily_api_key:
        try:
            async with asyncio.timeout(5.0):
                return await _searxng_search(client, query, top_k=top_k)
        except Exception as e:
            last_error = f"{type(e).__name__}"
    else:
        last_error = "unknown"
        for attempt in range(max_retries + 1):
            try:
                return await _searxng_search(client, query, top_k=top_k)
            except Exception as e:
                last_error = f"{type(e).__name__}"
                await asyncio.sleep(2**attempt + random.uniform(0, 1))
    try:
        hits = await _tavily_search(client, query, top_k=top_k)
        if hits:
            stats.fallback_used = True
            return hits
    except Exception as e:
        last_error = f"tavily_{type(e).__name__}"
    stats.errors.append(f"{query[:60]}: {last_error}")
    return []


async def web_search(
    queries: list[str],
    *,
    top_k: int = 5,
    timeout: float = 10.0,
    max_retries: int = 2,
    limit: int = 15,
    client: httpx.AsyncClient | None = None,
) -> tuple[list[SearchHit], SearchStats]:
    """Search all queries concurrently; dedupe by URL; cap total hits.

    Pass `client` in tests (e.g. MockTransport); otherwise one is created
    and closed here.
    """
    stats = SearchStats(queries=len(queries))
    if not queries:
        return [], stats
    if client is None:
        async with httpx.AsyncClient(
            timeout=timeout, headers={"User-Agent": "SignalSift-research/0.1"}
        ) as owned:
            return await _run_queries(owned, queries, stats, top_k, max_retries, limit)
    return await _run_queries(client, queries, stats, top_k, max_retries, limit)


async def _run_queries(
    client: httpx.AsyncClient,
    queries: list[str],
    stats: SearchStats,
    top_k: int,
    max_retries: int,
    limit: int,
) -> tuple[list[SearchHit], SearchStats]:
    batches = await asyncio.gather(
        *(
            _search_one(client, q, top_k=top_k, max_retries=max_retries, stats=stats)
            for q in queries
        )
    )
    seen: set[str] = set()
    hits: list[SearchHit] = []
    for batch in batches:
        for hit in batch:
            if hit.url not in seen:
                seen.add(hit.url)
                hits.append(hit)
            if len(hits) >= limit:
                break
    stats.hits = len(hits)
    return hits, stats
