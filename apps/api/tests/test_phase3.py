"""Phase 3 tests: grounding, verify loop, dedup, citation graph.

All offline (MockClient + fakes). The adversarial test pins the acceptance
bar: fabricated quotes must be dropped at >=30% on a hostile claim set.
"""

import asyncio
import sys
import time
import types

from agents.graph import build_graph
from agents.llm import MockClient
from agents.researcher import Researcher
from agents.verifier import MAX_ATTEMPTS, grounding_ok, nli_check, verify_claims
from tests.helpers import StubResearcher
from tools.citation_graph import build_citation_graph
from tools.dedup import dedupe_docs, group_near_duplicate_claims

EVIDENCE = {
    "https://a.example/1": "The Groq LPU delivers fast inference for large language models at low cost.",
    "https://b.example/2": "Pgvector adds vector similarity search to Postgres with an ivfflat index.",
}

GOOD = {
    "text": "Groq LPU gives fast LLM inference",
    "quote": "delivers fast inference for large language models",
    "url": "https://a.example/1",
}

SUPPORT = {"verdict": "supported", "reason": "entails"}
REJECT = {"verdict": "unsupported", "reason": "off-topic"}


def test_grounding_ok():
    assert grounding_ok(GOOD["quote"], EVIDENCE[GOOD["url"]]) is True
    assert grounding_ok("models cost nothing at all", EVIDENCE[GOOD["url"]]) is False
    assert grounding_ok("short", EVIDENCE[GOOD["url"]]) is False


async def test_nli_check_parses_verdict():
    ok, _ = await nli_check("c", "q", MockClient(payloads=[SUPPORT]))
    assert ok is True
    ok, _ = await nli_check("c", "q", MockClient(payloads=[REJECT]))
    assert ok is False


async def test_verify_supports_first_try():
    out = await verify_claims([dict(GOOD)], EVIDENCE, MockClient(payloads=[SUPPORT]))
    assert out[0]["verdict"] == "supported" and out[0]["attempts"] == 1


async def test_verify_retries_then_supports_fixed_claim():
    fixed = {"text": "Groq LPU is low cost", "quote": "at low cost"}
    out = await verify_claims(
        [dict(GOOD)],
        EVIDENCE,
        MockClient(payloads=[REJECT, fixed, SUPPORT]),
    )
    assert out[0]["verdict"] == "supported"
    assert out[0]["attempts"] == 2
    assert out[0]["text"] == fixed["text"]


async def test_verify_drops_after_max_attempts():
    # Grounded-but-rejected fixes keep the loop alive until the bound.
    bad_fix = {"text": "Groq is cheap", "quote": "at low cost"}
    out = await verify_claims(
        [dict(GOOD)],
        EVIDENCE,
        MockClient(payloads=[REJECT, bad_fix, REJECT, bad_fix, REJECT]),
    )
    assert out[0]["verdict"] == "unsupported"
    assert out[0]["attempts"] == MAX_ATTEMPTS


async def test_verify_stops_early_when_reextract_gives_up():
    out = await verify_claims(
        [dict(GOOD)],
        EVIDENCE,
        MockClient(payloads=[REJECT, {}]),
    )
    assert out[0]["verdict"] == "unsupported"
    assert out[0]["reason"] == "reextract_empty"
    assert out[0]["attempts"] == 1  # no point burning rounds after surrender


async def test_verify_drops_fabricated_quote_without_llm():
    client = MockClient(payloads=[])
    out = await verify_claims(
        [{**GOOD, "quote": "free solid gold deposited monthly"}],
        EVIDENCE,
        client,
    )
    assert out[0]["verdict"] == "unsupported"
    assert out[0]["reason"] == "quote_not_in_source"
    assert out[0]["attempts"] == 1
    assert client.calls == []  # deterministic drop costs zero LLM calls


async def test_adversarial_drop_rate_meets_bar():
    """4 fabricated of 10 claims -> 40% dropped, bar is >=30%."""
    real = " ".join(["evidence padding sentence"] * 20)
    evidence = {f"https://x.example/{i}": f"{real} unique marker {i} end" for i in range(6)}
    claims = [
        {"text": f"Claim {i}", "quote": f"unique marker {i}", "url": f"https://x.example/{i}"}
        for i in range(6)
    ] + [
        {"text": f"Fake {i}", "quote": f"fabricated nonsense {i}", "url": "https://x.example/0"}
        for i in range(4)
    ]
    out = await verify_claims(claims, evidence, MockClient(payloads=[SUPPORT] * 6))
    dropped = [c for c in out if c["verdict"] != "supported"]
    assert len(dropped) / len(out) >= 0.30
    assert all(c["text"].startswith("Fake") for c in dropped)


def test_dedupe_docs_exact_and_near():
    docs = [
        {"url": "https://a/1", "content_hash": "h1"},
        {"url": "https://a/2", "content_hash": "h1"},  # exact dupe
        {"url": "https://b/1", "content_hash": "h2"},
        {"url": "https://c/1", "content_hash": "h3"},
    ]
    out = dedupe_docs(docs, [[1.0, 0.0], [0.995, 0.099], [0.0, 1.0]])
    assert out["exact_dupes"] == 1
    assert out["near_dupes"] == 1  # h2 ~ h1 vector merged
    urls = [d["url"] for d in out["docs"]]
    assert urls == ["https://a/1", "https://c/1"]
    assert out["docs"][0]["merged_urls"] == ["https://b/1"]


def test_group_near_duplicate_claims():
    groups = group_near_duplicate_claims([{}, {}, {}], [[1.0, 0.0], [0.995, 0.099], [0.0, 1.0]])
    assert sorted(map(sorted, groups)) == [[0, 1], [2]]


def test_citation_graph_contested():
    claims = [
        {"text": "X is fast", "quote": "x is fast", "url": "https://a/1", "verdict": "supported"},
        {"text": "X is fast", "quote": "x is fast", "url": "https://b/2", "verdict": "supported"},
        {"text": "X is fast", "quote": "bogus", "url": "https://c/3", "verdict": "unsupported"},
        {"text": "Y is slow", "quote": "y is slow", "url": "https://a/1", "verdict": "supported"},
    ]
    docs = [{"url": "https://a/1", "title": "A"}, {"url": "https://b/2", "title": "B"}]
    graph = build_citation_graph(claims, docs)
    assert graph["stats"]["claims_supported"] == 3
    assert graph["stats"]["claims_dropped"] == 1
    by_text = {n["text"]: n for n in graph["claims"]}
    assert by_text["X is fast"]["contested"] is True
    assert by_text["Y is slow"]["contested"] is False
    assert sorted(by_text["X is fast"]["sources"]) == ["https://a/1", "https://b/2"]


async def test_researcher_near_dedupe_with_fake_embeddings():
    from tools.scrape import Doc

    async def fake_search(queries, **kw):
        return [], None

    async def fake_scrape(hits, **kw):
        body = " ".join(["same story different words here"] * 40)
        return (
            [
                Doc(url="https://n/1", title="N1", text=body + " alpha", content_hash="x1"),
                Doc(url="https://n/2", title="N2", text=body + " alpha!", content_hash="x2"),
                Doc(
                    url="https://n/3",
                    title="N3",
                    text="totally unrelated zebra quantum",
                    content_hash="x3",
                ),
            ],
            None,
        )

    async def fake_embed(texts):
        return [[1.0, 0.0] if "zebra" not in t else [0.0, 1.0] for t in texts]

    researcher = Researcher(
        extractor=MockClient(payloads=[]),
        search_fn=fake_search,
        scrape_fn=fake_scrape,
        embed_fn=fake_embed,
    )
    out = await researcher.run({"id": "sq-01", "question": "Q?", "search_queries": ["q"]})
    urls = [s["url"] for s in out["snippets"]]
    assert urls == ["https://n/1", "https://n/3"]
    assert out["snippets"][0]["merged_urls"] == ["https://n/2"]
    assert "evidence" in out and set(out["evidence"]) == set(urls)


async def test_concurrent_first_use_loads_model_once(monkeypatch):
    """Parallel researchers must share one model load (torch deadlocks otherwise)."""
    import tools.embed as embed_mod

    created = {"n": 0}

    class FakeST:
        def __init__(self, *a, **k):
            created["n"] += 1
            time.sleep(0.2)

        def encode(self, texts, normalize_embeddings=True):
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setitem(
        sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=FakeST)
    )
    monkeypatch.setattr(embed_mod, "_model", None)
    vecs = await asyncio.gather(*[embed_mod.embed_texts(["hello world"]) for _ in range(4)])
    assert created["n"] == 1
    assert all(v == [[1.0, 0.0]] for v in vecs)


async def test_graph_verify_finalize_end_to_end():
    evidence = {"https://example.com/sq-01/1": "signup takes five minutes total elapsed time"}
    claims = [
        {
            "text": "Signup takes five minutes",
            "quote": "signup takes five minutes",
            "url": "https://example.com/sq-01/1",
        },
        {
            "text": "Signup is free forever",
            "quote": "certified moon cheese",
            "url": "https://example.com/sq-01/1",
        },
    ]
    router = MockClient(payloads=[{"route": "research", "complexity": "simple"}])
    planner = MockClient(
        payloads=[
            {
                "sub_questions": [
                    {"id": "sq-01", "question": "Q?", "search_queries": ["q"], "priority": 1}
                ]
            }
        ]
    )
    nli = MockClient(payloads=[SUPPORT])
    graph = build_graph(
        router_client=router,
        planner_client=planner,
        researcher=StubResearcher(claims=claims, evidence=evidence),
        verifier_client=nli,
    )
    final = await graph.ainvoke({"query": "Q?"}, config={"configurable": {"thread_id": "e2e"}})
    by_id = {c["id"]: c for c in final["claims"]}
    assert by_id["sq-01-c1"]["verdict"] == "supported"
    assert by_id["sq-01-c2"]["verdict"] == "unsupported"
    stats = final["citation_graph"]["stats"]
    assert stats["claims_supported"] == 1 and stats["claims_dropped"] == 1
    nodes = [t["node"] for t in final["telemetry"]]
    assert nodes[:2] == ["router", "planner"] and nodes[-1] == "verify"
