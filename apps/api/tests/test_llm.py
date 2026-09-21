"""LLM client seam tests: protocol conformance + lenient JSON parsing.

Guards the Phase 6 incident where an edit stranded GroqClient methods as
unreachable nested defs — the module imported fine, but streaming broke at
runtime. `isinstance` against the runtime-checkable protocol fails loudly.
"""

import pytest

from agents.llm import GroqClient, LLMClient, MockClient, SleepyClient, _parse_json_lenient


def test_clients_satisfy_protocol():
    assert isinstance(GroqClient(api_key="test", model="test"), LLMClient)
    assert isinstance(MockClient(), LLMClient)
    assert isinstance(SleepyClient(), LLMClient)


def test_parse_json_lenient():
    assert _parse_json_lenient('{"a": 1}') == {"a": 1}
    assert _parse_json_lenient('Here you go:\n{"a": 1}\nDone.') == {"a": 1}
    with pytest.raises(ValueError):
        _parse_json_lenient("no braces here")


async def test_mock_streams_payload_in_chunks():
    chunks = [
        c async for c in MockClient(payloads=["hello world"]).astream_text(system="s", user="u")
    ]
    assert "".join(chunks) == "hello world"
    assert len(chunks) == 2
