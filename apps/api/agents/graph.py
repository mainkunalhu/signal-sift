"""Router -> planner -> Send fan-out -> researcher -> aggregate -> verify -> finalize.

`build_graph` injects all collaborators so tests run fully mocked while
production passes real Groq clients. The verify loop is bounded inside the
verify node (max 3 attempts per claim, then drop) — see `agents/verifier.py`.
Compiled with a MemorySaver checkpointer so runs can resume from the last
completed superstep.
"""

import time

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agents.llm import LLMClient
from agents.observability import traced
from agents.planner import plan_research
from agents.researcher import ResearcherLike
from agents.router import route_query
from agents.state import SupervisorState
from agents.verifier import verify_claims
from tools.citation_graph import build_citation_graph


def build_graph(
    *,
    router_client: LLMClient,
    planner_client: LLMClient,
    researcher: ResearcherLike | None = None,
    verifier_client: LLMClient | None = None,
    max_subquestions: int = 6,
):
    @traced("router")
    async def router_node(state: SupervisorState) -> dict:
        t0 = time.perf_counter()
        decision = await route_query(state["query"], router_client)
        return {
            "route": decision.model_dump(),
            "telemetry": [
                {
                    "node": "router",
                    "seconds": round(time.perf_counter() - t0, 3),
                    "route": decision.route,
                }
            ],
        }

    def route_edge(state: SupervisorState) -> str:
        return "planner" if state.get("route", {}).get("route") == "research" else END

    @traced("planner")
    async def planner_node(state: SupervisorState) -> dict:
        t0 = time.perf_counter()
        subs = await plan_research(
            state["query"], planner_client, max_subquestions=max_subquestions
        )
        return {
            "sub_questions": [s.model_dump() for s in subs],
            "telemetry": [
                {
                    "node": "planner",
                    "seconds": round(time.perf_counter() - t0, 3),
                    "sub_questions": len(subs),
                }
            ],
        }

    def fan_out(state: SupervisorState):
        subs = state.get("sub_questions", [])
        if not subs:
            return "aggregate"
        return [Send("researcher", {"sub_question": sq}) for sq in subs]

    @traced("researcher")
    async def researcher_node(payload: dict) -> dict:
        if researcher is None:
            raise RuntimeError("researcher not wired")
        sq = payload["sub_question"]
        result = await researcher.run(sq)
        stats = result.get("stats", {})
        return {
            "retrievals": {sq["id"]: result},
            "telemetry": [
                {
                    "node": "researcher",
                    "sub_question_id": sq["id"],
                    "docs": stats.get("docs", 0),
                    "claims": stats.get("claims", 0),
                }
            ],
        }

    async def aggregate_node(state: SupervisorState) -> dict:
        retrievals = state.get("retrievals", {})
        claims: list[dict] = []
        evidence: dict = {}
        for sq_id in sorted(retrievals):
            result = retrievals[sq_id]
            evidence.update(result.get("evidence", {}))
            for i, claim in enumerate(result.get("claims", [])):
                claims.append(
                    {
                        "id": f"{sq_id}-c{i + 1}",
                        "sub_question_id": sq_id,
                        "text": claim.get("text", ""),
                        "quote": claim.get("quote", ""),
                        "url": claim.get("url", ""),
                        "attempts": 0,
                        "verdict": "pending",
                    }
                )
        return {
            "claims": claims,
            "evidence": evidence,
            "telemetry": [
                {
                    "node": "aggregate",
                    "sources": len(retrievals),
                    "claims": len(claims),
                }
            ],
        }

    @traced("verify")
    async def verify_node(state: SupervisorState) -> dict:
        t0 = time.perf_counter()
        settled = await verify_claims(
            [c for c in state.get("claims", []) if c.get("verdict") == "pending"],
            state.get("evidence", {}),
            verifier_client,
        )
        by_id = {c["id"]: c for c in settled}
        claims = [by_id.get(c["id"], c) for c in state.get("claims", [])]
        kept = sum(1 for c in settled if c.get("verdict") == "supported")
        return {
            "claims": claims,
            "telemetry": [
                {
                    "node": "verify",
                    "seconds": round(time.perf_counter() - t0, 3),
                    "checked": len(settled),
                    "supported": kept,
                    "dropped": len(settled) - kept,
                }
            ],
        }

    async def finalize_node(state: SupervisorState) -> dict:
        docs: dict[str, dict] = {}
        for result in state.get("retrievals", {}).values():
            for snippet in result.get("snippets", []):
                docs.setdefault(
                    snippet["url"],
                    {"url": snippet["url"], "title": snippet.get("title", "")},
                )
        graph = build_citation_graph(state.get("claims", []), list(docs.values()))
        return {"citation_graph": graph}

    builder = StateGraph(SupervisorState)
    builder.add_node("router", router_node)
    builder.add_node("planner", planner_node)
    builder.add_node("researcher", researcher_node)
    builder.add_node("aggregate", aggregate_node)
    builder.add_node("verify", verify_node)
    builder.add_node("finalize", finalize_node)
    builder.add_edge(START, "router")
    builder.add_conditional_edges("router", route_edge, ["planner", END])
    builder.add_conditional_edges("planner", fan_out, ["researcher", "aggregate"])
    builder.add_edge("researcher", "aggregate")
    builder.add_edge("aggregate", "verify")
    builder.add_edge("verify", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=MemorySaver())
