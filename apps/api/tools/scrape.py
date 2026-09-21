"""Scrape + extract readable text: httpx fetch -> trafilatura -> truncate.

Contract: `scrape_many(hits, ...)` returns `Doc`s with `content_hash`
(sha256 of normalized text) so later stages can dedupe without re-fetching.
Unfetchable URLs are skipped silently and reported in stats — scrapers must
never fail a research run.
"""

import asyncio
import hashlib
import re
from dataclasses import dataclass, field

import httpx
import trafilatura

MAX_CHARS = 8000


@dataclass
class Doc:
    url: str
    title: str = ""
    text: str = ""
    content_hash: str = ""
    merged_urls: list[str] = field(default_factory=list)


@dataclass
class ScrapeStats:
    attempted: int = 0
    succeeded: int = 0
    skipped: int = 0


def normalize(text: str) -> str:
    text = (text or "").lower()
    return re.sub(r"\s+", " ", text).strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


async def _scrape_one(client: httpx.AsyncClient, url: str, title: str) -> Doc | None:
    try:
        resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()
        if "text/html" not in resp.headers.get("content-type", "text/html"):
            return None
        extracted = (
            await asyncio.to_thread(trafilatura.extract, resp.text, include_comments=False) or ""
        )
        text = normalize(extracted)[:MAX_CHARS]
        if len(text) < 200:  # boilerplate-only pages are noise
            return None
        return Doc(url=url, title=title, text=text, content_hash=content_hash(text))
    except Exception:
        return None


async def scrape_many(
    hits: list,
    *,
    timeout: float = 8.0,
    concurrency: int = 6,
    client: httpx.AsyncClient | None = None,
) -> tuple[list[Doc], ScrapeStats]:
    """Fetch hits concurrently; skip failures; dedupe identical bodies.

    Pass `client` in tests (e.g. MockTransport); otherwise one is created
    and closed here.
    """
    stats = ScrapeStats(attempted=len(hits))
    if not hits:
        return [], stats
    if client is None:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": "SignalSift-research/0.1"},
        ) as owned:
            return await _run_scrapes(owned, hits, stats, concurrency)
    return await _run_scrapes(client, hits, stats, concurrency)


async def _run_scrapes(
    client: httpx.AsyncClient,
    hits: list,
    stats: ScrapeStats,
    concurrency: int,
) -> tuple[list[Doc], ScrapeStats]:
    sem = asyncio.Semaphore(concurrency)

    async def bounded(hit) -> Doc | None:
        async with sem:
            return await _scrape_one(client, hit.url, hit.title)

    docs = await asyncio.gather(*(bounded(h) for h in hits))
    seen: set[str] = set()
    unique: list[Doc] = []
    for doc in docs:
        if doc is None:
            stats.skipped += 1
            continue
        if doc.content_hash in seen:
            stats.skipped += 1
            continue
        seen.add(doc.content_hash)
        unique.append(doc)
    stats.succeeded = len(unique)
    return unique, stats
