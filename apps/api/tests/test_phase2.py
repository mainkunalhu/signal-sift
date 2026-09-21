"""Phase 2 tests: search fallback, scrape dedupe, researcher pipeline.

All offline: `httpx.MockTransport` clients are injected into the tools, and
the researcher gets fake collaborators. No network, no API key.
"""

import httpx
import pytest

from agents.llm import MockClient
from agents.researcher import Researcher
from tools.scrape import content_hash, normalize, scrape_many
from tools.search import SearchHit, SearchStats, _search_one, web_search


@pytest.fixture(autouse=True)
def _no_tavily(monkeypatch):
    """Hermetic default: SearXNG-only path. Fallback test opts back in."""
    from config import settings

    monkeypatch.setattr(settings, "tavily_api_key", "")


SEARXNG_PAGE = {
    "results": [
        {"url": "https://a.example/x", "title": "A", "content": "snip a", "engine": "google"},
        {"url": "https://b.example/y", "title": "B", "content": "snip b"},
        {"url": "notaurl", "title": "junk"},
    ]
}

HTML = "<html><head><title>T</title></head><body><article><p>{}</p></article></body></html>"


def make_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_web_search_parses_and_dedupes_across_queries():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["format"] == "json"
        return httpx.Response(200, json=SEARXNG_PAGE)

    async with make_client(handler) as client:
        hits, stats = await web_search(["q1", "q2"], top_k=5, client=client)
    assert [h.url for h in hits] == ["https://a.example/x", "https://b.example/y"]
    assert hits[0].engine == "google"
    assert stats.queries == 2 and stats.hits == 2


async def test_search_one_retries_429_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={})
        return httpx.Response(200, json=SEARXNG_PAGE)

    async with make_client(handler) as client:
        hits = await _search_one(client, "q", top_k=5, max_retries=2, stats=SearchStats())
    assert calls["n"] == 2
    assert len(hits) == 2


async def test_search_one_falls_back_to_tavily(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "tavily_api_key", "test-key-not-real")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.tavily.com":
            return httpx.Response(
                200, json={"results": [{"url": "https://t.example/z", "title": "T"}]}
            )
        return httpx.Response(500, json={})

    async with make_client(handler) as client:
        stats = SearchStats()
        hits = await _search_one(client, "q", top_k=3, max_retries=0, stats=stats)
    assert [h.url for h in hits] == ["https://t.example/z"]
    assert hits[0].engine == "tavily"
    assert stats.fallback_used is True


async def test_search_one_records_error_when_everything_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    async with make_client(handler) as client:
        stats = SearchStats()
        hits = await _search_one(client, "q", top_k=3, max_retries=0, stats=stats)
    assert hits == [] and len(stats.errors) == 1


async def test_scrape_extracts_and_dedupes_identical_bodies():
    body = " ".join(["meaningful content sentence"] * 30)

    def handler(request: httpx.Request) -> httpx.Response:
        if "img" in str(request.url):
            return httpx.Response(200, headers={"content-type": "image/png"}, content=b"\x89png")
        return httpx.Response(200, headers={"content-type": "text/html"}, text=HTML.format(body))

    hits = [
        SearchHit(url="https://a.example/1"),
        SearchHit(url="https://a.example/2"),  # identical body -> dedupe
        SearchHit(url="https://img.example/i.png"),  # non-html -> skip
    ]
    async with make_client(handler) as client:
        docs, stats = await scrape_many(hits, client=client)
    assert len(docs) == 1
    assert stats.succeeded == 1 and stats.skipped == 2
    assert len(docs[0].text) <= 8000
    assert docs[0].content_hash == content_hash(docs[0].text)


async def test_normalize_and_hash_stable():
    assert normalize("  Hello\n\nWORLD  ") == "hello world"
    assert content_hash("Hello World") == content_hash("  hello\nworld ")


async def test_researcher_full_pipeline_with_fakes():
    async def fake_search(queries, **kw):
        return [SearchHit(url="https://a.example/1", title="A")], None

    async def fake_scrape(hits, **kw):
        from tools.scrape import Doc, ScrapeStats

        return (
            [
                Doc(
                    url="https://a.example/1",
                    title="A",
                    text="evidence body " * 50,
                    content_hash="h",
                )
            ],
            ScrapeStats(),
        )

    extractor = MockClient(
        payloads=[
            {
                "claims": [
                    {
                        "text": "A is fast",
                        "quote": "A is fast indeed",
                        "url": "https://a.example/1",
                    },
                    {"text": "Ghost", "quote": "nope", "url": "https://evil.example/"},
                    {"text": "", "quote": "empty", "url": "https://a.example/1"},
                ]
            }
        ]
    )
    researcher = Researcher(
        extractor=extractor, limit=2, search_fn=fake_search, scrape_fn=fake_scrape
    )
    out = await researcher.run(
        {"id": "sq-01", "question": "Is A fast?", "search_queries": ["A speed"]}
    )
    assert out["sub_question_id"] == "sq-01"
    assert len(out["snippets"]) == 1
    # unknown-url + empty claims dropped, valid one kept
    assert out["claims"] == [
        {"text": "A is fast", "quote": "A is fast indeed", "url": "https://a.example/1"}
    ]
    assert out["stats"]["docs"] == 1 and out["stats"]["claims"] == 1


async def test_researcher_degrades_gracefully():
    async def empty_search(queries, **kw):
        return [], None

    researcher = Researcher(extractor=MockClient(payloads=[]), search_fn=empty_search)
    out = await researcher.run({"id": "sq-09", "question": "Q?", "search_queries": []})
    assert out["snippets"] == [] and out["claims"] == []

    async def boom_search(queries, **kw):
        raise RuntimeError("net down")

    researcher2 = Researcher(extractor=MockClient(payloads=[]), search_fn=boom_search)
    out2 = await researcher2.run({"id": "sq-09", "question": "Q?", "search_queries": ["q"]})
    assert out2["snippets"] == [] and out2["claims"] == []
