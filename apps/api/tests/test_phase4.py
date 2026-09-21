"""Phase 4 tests: citation check, streaming assembly, repair loop, caps.

All offline via MockClient (astream yields the popped payload in 2 chunks).
"""

from agents.llm import MockClient
from agents.synthesizer import Synthesizer, check_citations

DOCS = [
    {"url": "https://a.example/1", "title": "A"},
    {"url": "https://b.example/2", "title": "B"},
]

CLAIMS = [
    {
        "text": "A is fast",
        "quotes": ["a is fast"],
        "sources": ["https://a.example/1"],
        "contested": False,
    },
    {
        "text": "B is slow",
        "quotes": ["b is slow"],
        "sources": ["https://b.example/2"],
        "contested": False,
    },
]


def test_check_citations_full_and_partial():
    full = "## Summary\nA is fast [1]\nB is slow [2]\n"
    assert check_citations(full, 2)["coverage"] == 1.0
    partial = "## Summary\nA is fast [1]\nB is slow\n"
    check = check_citations(partial, 2)
    assert check["coverage"] == 0.5 and len(check["uncited"]) == 1
    bad_range = "A is fast [9]\n"
    assert check_citations(bad_range, 2)["coverage"] == 0.0
    assert check_citations("## Just a heading\n", 2)["coverage"] == 1.0


async def test_synthesizer_streams_and_assembles():
    draft = "## Summary\nA is fast [1]\nB is slow [2]\n"
    tokens: list[str] = []

    async def collect(delta: str) -> None:
        tokens.append(delta)

    synth = Synthesizer(client=MockClient(payloads=[draft]))
    result = await synth.run(CLAIMS, DOCS, on_token=collect)
    assert "".join(tokens) == draft
    assert result.report_md == draft
    assert result.repaired is False and result.coverage == 1.0
    assert result.claims_used == 2 and result.docs_used == 2
    assert result.tokens_est > 0 and result.seconds >= 0


async def test_synthesizer_repairs_uncited_draft():
    draft = "## Summary\nA is fast\nB is slow [2]\n"
    fixed = "## Summary\nA is fast [1]\nB is slow [2]\n"
    client = MockClient(payloads=[draft, fixed])
    result = await Synthesizer(client=client).run(CLAIMS, DOCS)
    assert result.repaired is True
    assert result.report_md == fixed
    assert result.coverage == 1.0
    assert len(client.calls) == 2  # draft stream + one repair call


async def test_synthesizer_keeps_draft_when_repair_regresses():
    draft = "## Summary\nA is fast [1]\nB is slow\n"
    worse = "## Summary\nA is fast\nB is slow\n"
    client = MockClient(payloads=[draft, worse])
    result = await Synthesizer(client=client).run(CLAIMS, DOCS)
    assert result.report_md == draft  # worse repair discarded
    assert result.repaired is False
    assert result.coverage == 0.5


async def test_synthesizer_caps_claims_and_docs():
    many_claims = [
        {
            "text": f"C{i}",
            "quotes": ["q"],
            "sources": [f"https://x.example/{i}"],
            "contested": False,
        }
        for i in range(20)
    ]
    many_docs = [{"url": f"https://x.example/{i}", "title": "X"} for i in range(20)]
    client = MockClient(payloads=["## Summary\nCited [1]\n"])
    result = await Synthesizer(client=client).run(many_claims, many_docs)
    assert result.claims_used == 15 and result.docs_used == 15
    prompt = client.calls[0]["user"]
    assert "C19" not in prompt and "[15]" in prompt


async def test_synthesizer_empty_inputs():
    result = await Synthesizer(client=MockClient(payloads=["## Summary\nNothing cited.\n"])).run(
        [], []
    )
    assert result.claims_used == 0 and result.docs_used == 0
    assert result.coverage == 0.0  # honest signal, no repair possible without sources
