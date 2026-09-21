# SignalSift — Groq Deep-Research Swarm

A Groq-powered alternative to Perplexity Deep Research. Ask one hard question,
parallel agents research 10–20 sources, a verifier rejects ungrounded claims,
and you get a streaming cited report. No local GPU needed — everything via Groq API.

`Groq research swarm, 8 parallel agents, faithfulness 0.93, p95 29s free-tier, full trace`

## How it works

```
Query (Next.js :3000) → Hono gateway (:3001) → FastAPI SSE (:8000)
  Router (gpt-oss-20b) → Planner (gpt-oss-120b, 5–8 sub-questions)
  → LangGraph Send fan-out → N × Researcher (SearXNG/Tavily → trafilatura → claim extract)
  → dedup (sha256 + pgvector cosine) + citation graph
  → Verifier (20b NLI, grounding check, max 3 tries, drop ungrounded)
  → Synthesizer (120b, streaming markdown, citation check + repair)
  → Neon Postgres + Phoenix Cloud tracing
```

## Quickstart

```bash
cp .env.example .env   # fill GROQ_API_KEY, DATABASE_URL (Neon), TAVILY_API_KEY (optional)
make sync              # uv sync + bun installs
make dev               # API :8000 (second terminal)
make gateway           # Hono :3001
make web               # Next.js :3000
make eval              # small eval: 3 tasks (cheap on API credits)
```

Full 30-task eval (only with quota to spare):
`cd apps/api && uv run python -m evals.scorer --max-subquestions 4`.
Unset `TAVILY_API_KEY` for SearXNG-only mode (slower, free).

## Layout

```
apps/api/{agents,tools,routes,db,evals}  # FastAPI + LangGraph swarm (uv)
apps/web/src/{app,components,lib}        # Next.js report UI (bun, create-next-app)
apps/gateway/src                         # Hono proxy: rate-limit, CORS (bun)
packages/shared/src/types.ts             # SSE/domain contract
infra/schema.sql                         # Postgres + pgvector DDL
docs/eval_results.json                   # 30-task baseline report
```

## Eval results (30-task baseline, `docs/eval_results.json`)

Held-out 120b judge over supported claims; 4 sub-questions/task; Groq free tier.

| Metric | Baseline | Target | Notes |
|---|---|---|---|
| Faithfulness | **0.927** (317 claims) | ≥ 0.84 | by category: factual 0.964, comparison 0.903, contested 0.882, longtail 1.0 |
| Citation precision | 0.627 | 1.0 | repair-regression bug found by this eval, fixed after (see below) |
| Supported rate | 0.676 | — | verifier drops ~1/3 of extracted claims |
| p50 / p95 | 24s / 29s | p95 18s | p95 18s needs paid tier (higher concurrency, no free-tier queueing) |

Honest notes: 3/30 tasks short-circuit at the router (judged answerable from
knowledge — router calibration signal, not failure). A repair pass that could
*strip* citations was caught by the baseline and fixed (synthesizer now keeps
the highest-coverage version; regression-tested). A tuned re-run of the
affected tasks is pending API quota reset.

## Key engineering decisions

- LangGraph `Send` fan-out with `merge_dicts` reducers (smoke-tested for real parallelism)
- Free-tier survival: semaphore-4 throttle, 429 backoff+jitter, SearXNG→Tavily fast fallback
- Anti-hallucination: verbatim-quote grounding check (zero LLM cost) + NLI + strict re-extract, max 3 tries
- Embeddings pinned to CPU (Apple Metal crashes under concurrent inference)
- Batch OTel export (sync export added ~100s to a 4-way run)
- Offline-first tests: 38 green, `httpx.MockTransport` + injected fakes, no key/network needed
