"""Phase 1 tests: reducers, router/planner units, Send fan-out smoke test.

The smoke test fails if `Send` stops being concurrent: with 3 sub-questions
at 0.4s latency each, a sequential run costs ~2.0s while a parallel fan-out
costs ~1.2s. No API key or network needed.
"""

import time

from agents.graph import build_graph
from agents.llm import MockClient, SleepyClient
from agents.planner import plan_research
from agents.router import heuristic_fallback, route_query
from agents.state import append_list, merge_dicts
from tests.helpers import StubResearcher

THREE_SUBS = {
    "sub_questions": [
        {"id": "sq-01", "question": "Q1?", "search_queries": ["q1"], "priority": 1},
        {"id": "sq-02", "question": "Q2?", "search_queries": ["q2"], "priority": 2},
        {"id": "sq-03", "question": "Q3?", "search_queries": ["q3"], "priority": 3},
    ]
}


def test_merge_dicts_is_order_independent():
    a = {"sq-01": [1]}
    b = {"sq-02": [2]}
    assert merge_dicts(a, b) == merge_dicts(b, a) == {"sq-01": [1], "sq-02": [2]}
    assert merge_dicts(None, b) == b
    assert append_list([1], [2]) == [1, 2]


async def test_router_returns_research_for_question():
    client = MockClient(payloads=[{"route": "research", "complexity": "hard", "reason": "t"}])
    decision = await route_query("Compare Groq vs Cerebras for agents?", client)
    assert decision.route == "research"
    assert decision.complexity == "hard"


async def test_router_falls_back_on_garbage():
    decision = await route_query("What is pgvector?", MockClient(payloads=["nope"]))
    assert decision.route == "research"  # heuristic: contains 'what'
    assert heuristic_fallback("").route == "reject"


async def test_planner_clamps_to_max_and_sorts_by_priority():
    many = {
        "sub_questions": [
            {
                "id": f"sq-{i:02d}",
                "question": f"Q{i}?",
                "search_queries": ["q"],
                "priority": (i % 3) + 1,
            }
            for i in range(1, 10)
        ]
    }
    subs = await plan_research("test", MockClient(payloads=[many]), max_subquestions=6)
    assert len(subs) == 6
    assert [s.priority for s in subs] == sorted(s.priority for s in subs)


async def test_planner_falls_back_to_single_item():
    subs = await plan_research("What is X?", MockClient(payloads=[{}, {}]))
    assert len(subs) == 1 and subs[0].id == "sq-01"


async def test_graph_parallel_smoke():
    """3 researchers x 0.4s must finish well under the ~2.0s sequential cost."""
    client = SleepyClient(delay=0.4, planner_payload=THREE_SUBS)
    graph = build_graph(
        router_client=client,
        planner_client=client,
        researcher=StubResearcher(delay=0.4),
    )
    t0 = time.perf_counter()
    final = await graph.ainvoke(
        {"query": "Smoke test query?"},
        config={"configurable": {"thread_id": "smoke"}},
    )
    wall = time.perf_counter() - t0
    assert set(final.get("retrievals", {})) == {"sq-01", "sq-02", "sq-03"}
    assert wall < 1.8, f"fan-out looks sequential: {wall:.2f}s"
    nodes = [t["node"] for t in final.get("telemetry", [])]
    assert nodes[0] == "router" and "aggregate" in nodes


async def test_reject_short_circuits_before_planner():
    client = MockClient(payloads=[{"route": "reject", "complexity": "simple", "reason": "t"}])
    graph = build_graph(router_client=client, planner_client=client)
    final = await graph.ainvoke(
        {"query": "asdfgh"},
        config={"configurable": {"thread_id": "reject"}},
    )
    assert final["route"]["route"] == "reject"
    assert final.get("retrievals", {}) == {}
    assert "sub_questions" not in final
