"""POST /api/research — SSE: plan -> search_progress* -> claim_verified* -> token* -> done.

Streams retrieval progress, per-claim verdicts, then the synthesized report
token-by-token. The canonical checked `report_md` ships in `done` (a repair
pass may supersede the streamed draft tokens).
"""

import asyncio
import json
import time
import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from agents.graph import build_graph
from agents.llm import GroqClient
from agents.researcher import Researcher
from agents.synthesizer import SynthesisResult, Synthesizer
from config import settings
from db.store import save_run
from tools.embed import embed_texts
from tools.scrape import content_hash as text_hash

router = APIRouter()


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    max_subquestions: int = Field(default=6, ge=1, le=8)
    max_sources: int = Field(default=15, ge=1, le=30)


def _event(name: str, payload: dict) -> dict:
    return {"event": name, "data": json.dumps(payload)}


def _build_production_graph(max_subquestions: int):
    api_key = settings.groq_api_key
    return build_graph(
        router_client=GroqClient(api_key=api_key, model=settings.groq_fast_model, name="router"),
        planner_client=GroqClient(
            api_key=api_key, model=settings.groq_planner_model, name="planner"
        ),
        researcher=Researcher(
            extractor=GroqClient(
                api_key=api_key, model=settings.groq_planner_model, name="extractor"
            ),
            limit=settings.max_concurrent_researchers,
            embed_fn=embed_texts,
        ),
        verifier_client=GroqClient(
            api_key=api_key, model=settings.groq_fast_model, name="verifier"
        ),
        max_subquestions=max_subquestions,
    )


def _build_synthesizer():
    return Synthesizer(
        client=GroqClient(
            api_key=settings.groq_api_key,
            model=settings.groq_planner_model,
            name="synthesizer",
        )
    )


@router.post("/api/research")
async def research(req: ResearchRequest):
    graph = _build_production_graph(req.max_subquestions)
    thread_id = f"web-{uuid.uuid4().hex[:8]}"

    async def gen():
        t0 = time.perf_counter()
        results: dict = {}
        graph_state: dict = {}
        async for chunk in graph.astream(
            {"query": req.query},
            config={"configurable": {"thread_id": thread_id}},
            stream_mode="updates",
        ):
            if "router" in chunk:
                route = chunk["router"].get("route", {})
                if route.get("route") != "research":
                    yield _event("done", {"route": route, "reason": "not_research"})
                    return
            elif "planner" in chunk:
                yield _event("plan", {"sub_questions": chunk["planner"].get("sub_questions", [])})
            elif "researcher" in chunk:
                for sq_id, result in chunk["researcher"].get("retrievals", {}).items():
                    results[sq_id] = result
                    yield _event(
                        "search_progress",
                        {
                            "sub_q_id": sq_id,
                            "status": "done",
                            "urls": [s["url"] for s in result.get("snippets", [])],
                            "claims": len(result.get("claims", [])),
                        },
                    )
            elif "verify" in chunk:
                for claim in chunk["verify"].get("claims", []):
                    if claim.get("verdict") in ("supported", "unsupported"):
                        yield _event(
                            "claim_verified",
                            {
                                "claim_id": claim.get("id"),
                                "verdict": claim.get("verdict"),
                                "url": claim.get("url"),
                                "attempts": claim.get("attempts", 0),
                            },
                        )
            elif "finalize" in chunk:
                graph_state = chunk["finalize"].get("citation_graph", {})
        public_results = {
            sq_id: {k: v for k, v in result.items() if k != "evidence"}
            for sq_id, result in results.items()
        }
        citations = [
            {"url": s["url"], "title": s["title"]}
            for r in public_results.values()
            for s in r.get("snippets", [])
        ][: req.max_sources]

        # Synthesis runs concurrently while tokens drain live: produce and
        # consume overlap instead of buffering the whole draft first.
        gen_queue: asyncio.Queue = asyncio.Queue()
        synth_task = asyncio.create_task(_synthesize_with_tokens(graph_state, gen_queue))
        while True:
            try:
                yield await asyncio.wait_for(gen_queue.get(), timeout=0.2)
            except TimeoutError:
                if synth_task.done():
                    break
        while not gen_queue.empty():
            yield await gen_queue.get()
        synthesis = await synth_task

        query_id = await _persist_best_effort(req, public_results, graph_state)
        yield _event(
            "done",
            {
                "query_id": query_id,
                "results": public_results,
                "citations": citations,
                "citation_graph": graph_state,
                "report_md": synthesis.report_md if synthesis else "",
                "synth": (
                    {
                        "repaired": synthesis.repaired,
                        "coverage": synthesis.coverage,
                        "claims_used": synthesis.claims_used,
                        "docs_used": synthesis.docs_used,
                        "tokens_est": synthesis.tokens_est,
                        "seconds": synthesis.seconds,
                    }
                    if synthesis
                    else None
                ),
                "latency_ms": int((time.perf_counter() - t0) * 1000),
            },
        )

    return EventSourceResponse(gen())


async def _synthesize_with_tokens(graph_state: dict, queue) -> SynthesisResult | None:
    """Run synthesis, forwarding draft tokens into the SSE queue. Never raises."""
    try:
        nodes = graph_state.get("claims", [])
        docs = graph_state.get("docs", [])
        if not nodes or not docs:
            return None

        async def on_token(delta: str) -> None:
            await queue.put(_event("token", {"delta": delta}))

        return await _build_synthesizer().run(nodes, docs, on_token=on_token)
    except Exception:
        return None


async def _persist_best_effort(
    req: ResearchRequest, results: dict, graph_state: dict
) -> str | None:
    """Save run + doc embeddings for dedup history. Never fails the request."""
    try:
        docs, seen, texts = [], set(), []
        for result in results.values():
            for snippet in result.get("snippets", []):
                if snippet["url"] in seen:
                    continue
                seen.add(snippet["url"])
                docs.append(
                    {
                        "url": snippet["url"],
                        "title": snippet.get("title", ""),
                        # Snippet-level hash: stable within a run, enough for
                        # dedup history until full-text persistence (Phase 6).
                        "content_hash": text_hash(snippet.get("text", "")),
                        "embedding": None,
                    }
                )
                texts.append(snippet.get("text", ""))
        if docs:
            vectors = await embed_texts(texts)
            for doc, vec in zip(docs, vectors):
                doc["embedding"] = vec
        return await save_run(
            query=req.query,
            plan=[],
            docs=docs,
            claims=[
                {
                    "text": node.get("text", ""),
                    "quote": (node.get("quotes") or [""])[0],
                    "url": (node.get("sources") or [""])[0],
                    "verdict": "supported",
                }
                for node in graph_state.get("claims", [])
                if node.get("sources")
            ],
        )
    except Exception:
        return None
