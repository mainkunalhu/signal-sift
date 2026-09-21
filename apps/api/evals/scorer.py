"""Eval scorer: 30 research tasks through the production graph.

Per task: wall latency, retrieval counts, verifier verdicts, held-out 120b
faithfulness judgments over supported claims, report citation coverage.
Writes docs/eval_results.json incrementally (safe for long runs) and prints
a summary. Traces go to the Phoenix `signalsift-eval` project.

Run: uv run python -m evals.scorer [--limit N] [--category factual]
     [--max-subquestions 4] [--out ../../docs/eval_results.json]
"""

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import yaml

from agents.graph import build_graph
from agents.llm import GroqClient
from agents.observability import setup_tracing
from agents.researcher import Researcher
from agents.synthesizer import Synthesizer
from config import settings
from tools.embed import embed_texts

JUDGE_SYSTEM = """You audit groundedness of research claims. Each claim has a quote
copied from its cited source. Judge whether the quote substantiates the claim.
Return JSON only: {"judgments": [{"i": 0, "faithful": true, "reason": "short"}]}
Rules:
- faithful=true only if the quote directly states or clearly entails the claim.
- Topical-but-vague quotes, contradictions, or leaps -> faithful=false.
- Judge the text in front of you. No outside knowledge."""

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent  # evals -> api -> signal-sift
DEFAULT_OUT = REPO_ROOT / "docs" / "eval_results.json"


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[rank]


def load_tasks(
    category: str | None, limit: int | None, ids: str | None
) -> list[dict]:
    tasks = yaml.safe_load((HERE / "tasks.yaml").read_text())
    if category:
        tasks = [t for t in tasks if t["category"] == category]
    if ids:
        wanted = {i.strip() for i in ids.split(",")}
        tasks = [t for t in tasks if t["id"] in wanted]
    return tasks[:limit] if limit else tasks


async def judge_claims(claims: list[dict], client: GroqClient) -> dict:
    """One judge call per task over all supported claims. Never raises."""
    if not claims:
        return {"faithful": 0, "total": 0, "details": []}
    items = "\n".join(
        f"[{i}] Claim: {c.get('text', '')}\nQuote: {c.get('quote', '')}"
        for i, c in enumerate(claims)
    )
    try:
        data = await client.acomplete_json(
            system=JUDGE_SYSTEM,
            user=f"Judge each claim:\n{items}\nReturn JSON only.",
        )
    except Exception as e:
        return {"faithful": 0, "total": len(claims), "details": [], "error": type(e).__name__}
    by_i = {j.get("i"): j for j in data.get("judgments", []) if isinstance(j, dict)}
    details = [
        {
            "text": c.get("text", "")[:200],
            "faithful": bool(by_i.get(i, {}).get("faithful", False)),
            "reason": str(by_i.get(i, {}).get("reason", "no_judgment"))[:200],
        }
        for i, c in enumerate(claims)
    ]
    return {
        "faithful": sum(1 for d in details if d["faithful"]),
        "total": len(details),
        "details": details,
    }


async def run_task(task: dict, clients: dict, max_subquestions: int) -> dict:
    """Full pipeline for one task: retrieve -> verify -> synthesize -> judge."""
    t0 = time.perf_counter()
    graph = build_graph(
        router_client=clients["router"],
        planner_client=clients["planner"],
        researcher=Researcher(
            extractor=clients["extractor"],
            limit=settings.max_concurrent_researchers,
            embed_fn=embed_texts,
        ),
        verifier_client=clients["verifier"],
        max_subquestions=max_subquestions,
    )
    try:
        final = await graph.ainvoke(
            {"query": task["query"]},
            config={"configurable": {"thread_id": f"eval-{task['id']}"}},
        )
    except Exception as e:
        return {"id": task["id"], "category": task["category"], "error": f"{type(e).__name__}"}

    claims = final.get("claims", [])
    supported = [c for c in claims if c.get("verdict") == "supported"]
    graph_state = final.get("citation_graph", {}) or {}
    docs = graph_state.get("docs", [])

    synth = await Synthesizer(client=clients["synth"]).run(graph_state.get("claims", []), docs)
    coverage = synth.coverage
    judged = await judge_claims(
        [{"text": c.get("text", ""), "quote": c.get("quote", "")} for c in supported],
        clients["judge"],
    )
    wall_ms = int((time.perf_counter() - t0) * 1000)
    retrievals = final.get("retrievals", {})
    return {
        "id": task["id"],
        "category": task["category"],
        "wall_ms": wall_ms,
        "sub_questions": len(final.get("sub_questions", [])),
        "docs": sum(len(r.get("snippets", [])) for r in retrievals.values()),
        "claims_extracted": len(claims),
        "claims_supported": len(supported),
        "faithful": judged["faithful"],
        "faithful_total": judged["total"],
        "citation_coverage": round(coverage, 3),
        "contested": graph_state.get("stats", {}).get("contested", 0),
        "synth_seconds": synth.seconds,
        "repaired": synth.repaired,
    }


def summarize(records: list[dict]) -> dict:
    ok = [r for r in records if "error" not in r]
    faithful = sum(r["faithful"] for r in ok)
    judged_total = sum(r["faithful_total"] for r in ok)
    walls = [r["wall_ms"] for r in ok]
    by_cat: dict[str, dict] = {}
    for cat in ("factual", "comparison", "contested", "longtail"):
        cat_rs = [r for r in ok if r["category"] == cat]
        if cat_rs:
            ft = sum(r["faithful_total"] for r in cat_rs) or 1
            by_cat[cat] = {
                "n": len(cat_rs),
                "faithfulness": round(sum(r["faithful"] for r in cat_rs) / ft, 3),
                "p50_ms": int(percentile([r["wall_ms"] for r in cat_rs], 50)),
            }
    return {
        "tasks": len(records),
        "errors": len(records) - len(ok),
        "faithfulness": round(faithful / (judged_total or 1), 3),
        "claims_judged": judged_total,
        "citation_precision": round(statistics.fmean([r["citation_coverage"] for r in ok]), 3)
        if ok
        else 0.0,
        "supported_rate": round(
            sum(r["claims_supported"] for r in ok) / (sum(r["claims_extracted"] for r in ok) or 1),
            3,
        ),
        "p50_ms": int(percentile(walls, 50)),
        "p95_ms": int(percentile(walls, 95)),
        "by_category": by_cat,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--category", type=str, default=None)
    parser.add_argument("--ids", type=str, default=None,
                        help="comma-separated task ids for targeted re-runs")
    parser.add_argument("--max-subquestions", type=int, default=4)
    parser.add_argument("--out", type=str, default=str(DEFAULT_OUT))
    args = parser.parse_args()

    setup_tracing(project_name="signalsift-eval")
    key = settings.groq_api_key
    clients = {
        "router": GroqClient(api_key=key, model=settings.groq_fast_model, name="eval-router"),
        "planner": GroqClient(api_key=key, model=settings.groq_planner_model, name="eval-planner"),
        "extractor": GroqClient(
            api_key=key, model=settings.groq_planner_model, name="eval-extract"
        ),
        "verifier": GroqClient(api_key=key, model=settings.groq_fast_model, name="eval-verify"),
        "synth": GroqClient(api_key=key, model=settings.groq_planner_model, name="eval-synth"),
        "judge": GroqClient(api_key=key, model=settings.groq_planner_model, name="eval-judge"),
    }
    tasks = load_tasks(args.category, args.limit, args.ids)
    print(f"eval: {len(tasks)} tasks, max_subquestions={args.max_subquestions}")

    records: list[dict] = []
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    for i, task in enumerate(tasks, 1):
        record = await run_task(task, clients, args.max_subquestions)
        records.append(record)
        if "error" in record:
            print(f"[{i}/{len(tasks)}] {task['id']} ERROR {record['error']}", flush=True)
        else:
            print(
                f"[{i}/{len(tasks)}] {task['id']} wall={record['wall_ms'] // 1000}s "
                f"faithful={record['faithful']}/{record['faithful_total']} "
                f"cov={record['citation_coverage']} docs={record['docs']}",
                flush=True,
            )
        out_path.write_text(json.dumps({"summary": summarize(records), "tasks": records}, indent=2))
    print(json.dumps(summarize(records), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
