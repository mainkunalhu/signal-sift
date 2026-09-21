# SignalSift — Groq Deep-Research Swarm: Full Build Plan

> A Groq-powered alternative to Perplexity Deep Research.
> Query → router → planner (5–8 sub-questions) → parallel researchers → dedup + citation graph → verifier (max 3 retries) → streaming cited report.
> **Hiring line:** `Groq research swarm, 8 parallel agents, faithfulness 0.84, p95 18s, full trace`.

**Choices locked for v1:** Full vision · Cloud-managed infra (Neon/Supabase + public SearXNG) · Groq free-tier (concurrency 4, flag to 8) · Perplexity-clone UI.

**Critical model update (Aug 2026):** `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` are **deprecated/shutdown on Groq free tier**. This plan uses:
- `openai/gpt-oss-120b` → planner, researcher, synthesizer (was 70b-versatile)
- `openai/gpt-oss-20b` → router, verifier (was 8b-instant)
- Fallback: `qwen/qwen3-32b` / `llama-3.3-70b-specdec` if listed.
- All model IDs via env, never hardcoded.

---

## 0. Folder Structure (created)

```
signal-sift/
├── BUILD_PLAN.md               # this file
├── .env.example
├── .gitignore
├── Makefile                    # make dev/api/web/eval shortcuts
├── docker-compose.yml          # optional: Phoenix only (DB is cloud)
├── apps/
│   ├── api/                    # Python FastAPI + LangGraph swarm
│   │   ├── main.py             # FastAPI app + SSE route wiring
│   │   ├── config.py           # env + model IDs + limits
│   │   ├── requirements.txt
│   │   ├── agents/
│   │   │   ├── graph.py        # StateGraph + Send fan-out/fan-in topology
│   │   │   ├── state.py        # SupervisorState + reducers
│   │   │   ├── router.py       # gpt-oss-20b classifier
│   │   │   ├── planner.py      # gpt-oss-120b → 5-8 sub-questions
│   │   │   ├── researcher.py   # parallel search+scrape+extract
│   │   │   ├── verifier.py     # NLI entailment, 3 retries
│   │   │   └── synthesizer.py  # final streaming report
│   │   ├── tools/
│   │   │   ├── search.py       # SearXNG (+ Tavily fallback)
│   │   │   ├── scrape.py       # httpx + trafilatura
│   │   │   ├── embed.py        # bge-small / nomic-embed
│   │   │   ├── dedup.py        # hash + pgvector cosine
│   │   │   └── citation_graph.py
│   │   ├── routes/
│   │   │   ├── research.py     # POST /api/research (SSE)
│   │   │   └── health.py
│   │   ├── db/
│   │   │   ├── models.py       # queries, documents, claims
│   │   │   └── store.py        # pgvector helpers
│   │   └── evals/
│   │       ├── tasks.yaml      # 30 research tasks
│   │       └── scorer.py       # faithfulness + latency
│   ├── web/                    # Next.js (canonical `create-next-app`, bun)
│   │   ├── src/app/page.tsx    # query box + streaming view
│   │   ├── src/components/
│   │   │   ├── ReportStream.tsx
│   │   │   ├── SourcesPanel.tsx
│   │   │   └── TraceView.tsx
│   │   └── src/lib/sse.ts      # SSE client
│   └── gateway/                # Hono proxy (Phase 5)
│       └── src/index.ts
├── packages/shared/src/types.ts # shared Claim/Citation/SSE event types
├── infra/
│   ├── schema.sql              # Postgres + pgvector DDL
│   └── searxng.settings.yml
└── docs/                       # architecture notes, prompts, eval results
```

---

## 1. System Architecture

```
[Next.js :3000] → [Hono :3001] → [FastAPI :8000 /api/research SSE]
                                        │
  Router (20b, <500ms) → Planner (120b, 5-8 sub-qs, JSON)
    → LangGraph Send fan-out → N × Researcher (120b)
    │     each: SearXNG top-5 → scrape top-3 → extract claims+quotes
    → Fan-in: dedup (sha256 + cosine>0.92) + citation graph
    → Verifier (20b, supported|unsupported|contested, max 3 retries)
    → Synthesizer (120b, markdown + [1][2][3], streaming)
                                        │
              [Neon pgvector] + [Phoenix tracing]
```

**Key patterns:**
- LangGraph `Send` for dynamic fan-out (N unknown until planner runs).
- Reducers: `Annotated[dict, merge_dicts]` for per-sub-q writes, `Annotated[list, add]` for token logs. Without these parallel writes clobber each other.
- `asyncio.gather` + `asyncio.Semaphore(4)` for free-tier safety (flag to 8 on paid).
- Every parallel node wrapped in try/except → sentinel value so one failure never kills the superstep.

---

## 2. API & Data Contracts

### POST /api/research (SSE)
Request: `{ "query": "...", "max_subquestions": 6, "max_sources": 15 }`
Events:
```
event: plan             data: {sub_questions: [{id, question, search_queries[]}]}
event: search_progress  data: {sub_q_id, status: searching|scraping|extracting|done, urls: []}
event: claim_verified   data: {claim_id, verdict, citations: [doc_id]}
event: token            data: {delta: "## Summary\n..."}
event: done             data: {report_md, citations: [{id, url, title}], latency_ms, faithfulness}
```

### DB (infra/schema.sql)
- `queries(id uuid, text text, plan_json jsonb, created_at timestamptz)`
- `documents(id uuid, query_id uuid, url text, title text, content_hash text unique, embedding vector(384))`
- `claims(id uuid, doc_id uuid, text text, embedding vector(384), verdict text, citations jsonb)`

---

## 3. Context Budget (128k hard cap)

| Stage | Budget |
|---|---|
| Researcher (each) | 3 docs × 2k + prompt 2k = ~8k |
| Fan-in (aggregator) | top 20 docs × 1.5k = ~30k |
| Verifier | 1 claim + 2 chunks = ~1k per call |
| Synthesizer | top 15 verified claims + outline = ~12k |
| Total worst-case | ~50k — safe under 128k, headroom for 8-way fan-out |

Rules: truncate scraped HTML to 8k chars via trafilatura, rank+cut before synth, never pass raw search dumps to planner.

---

## 4. Anti-Hallucination Loop

1. Extractor must return `quote` verbatim per claim.
2. Verifier NLI: `claim + evidence → supported|unsupported|contested`.
3. Unsupported → one re-scrape with refined query → re-verify. Max 3 retries, then drop.
4. Contested (two sources disagree) → keep both, mark `contested:true`, synthesizer hedges ("Sources disagree...").
5. Synthesizer system prompt bans uncited sentences; post-check regex ensures every paragraph has `[n]`.

---

## Phase 0 — Scaffolding (0.5 day)

**Goal:** repo runs, Groq reachable, cloud DB reachable.
- [ ] `python -m venv`, `pip install fastapi sse-starlette langgraph groq trafilatura pgvector`
- [ ] `.env` from `.env.example` (`GROQ_API_KEY`, `GROQ_PLANNER_MODEL=openai/gpt-oss-120b`, `GROQ_FAST_MODEL=openai/gpt-oss-20b`, `DATABASE_URL`, `SEARXNG_URL=https://searx.be`, `TAVILY_API_KEY=` optional)
- [ ] Create Neon project → enable `pgvector` + `pg_trgm` → run `infra/schema.sql`
- [ ] `GET /health` returns `{groq_ok: true, db_ok: true}`
- [ ] `make dev` runs API on :8000

**Accept:** `curl localhost:8000/health` green + 1 Groq test call succeeds.

## Phase 1 — Router + Planner + Graph Skeleton (1 day)

**Goal:** LangGraph topology works end-to-end with mocked researchers.
- [ ] `agents/state.py`: `SupervisorState` with `merge_dicts` / `add` reducers
- [ ] `agents/router.py`: 20b JSON `{route: research|chat|reject, complexity}`
- [ ] `agents/planner.py`: 120b structured output, 5–8 sub-questions, each with 2–3 search queries
- [ ] `agents/graph.py`: `START → router → planner → Send fan-out → researcher → fan-in → END`, checkpointer `MemorySaver`
- [ ] Phoenix tracing span per node
- [ ] Smoke test with `SleepyClient` (no API key, proves parallelism in ~6s)

**Accept:** mocked 3-sub-q run fans out in parallel; state not clobbered (test: all 3 retrievals present).

## Phase 2 — Researcher: Search + Scrape + Extract (2 days)

**Goal:** real sources flowing, free-tier safe.
- [ ] `tools/search.py`: SearXNG `/search?q=&format=json`, `topK=5`, timeout 10s, Tavily fallback on 429/5xx
- [ ] `tools/scrape.py`: `httpx` + `trafilatura.extract`, 8s timeout, 8k char cap, Playwright fallback stub
- [ ] `agents/researcher.py`: per sub-q → search → scrape top-3 → 120b extract `{claims[], quotes[]}`, semaphore 4, exponential backoff+jitter on 429
- [ ] SSE `search_progress` events per sub-q
- [ ] Cache by `content_hash` to avoid re-scrape

**Accept:** 1 hard query → 10–15 docs in <12s on free tier; 429s retried not crashed.

## Phase 3 — Dedup + Citation Graph + Verifier (1.5 days)

**Goal:** no duplicate sources, no ungrounded claims.
- [ ] `tools/embed.py`: `BAAI/bge-small-en-v1.5` (384-d, CPU) initially; swap to nomic later
- [ ] `tools/dedup.py`: exact `sha256(normalized)` → pgvector cosine >0.92 near-dedup
- [ ] `tools/citation_graph.py`: `claim_id → [doc_ids]`, contested detection
- [ ] `agents/verifier.py`: 20b NLI, conditional edge `verify → retry_research (max 3) → drop|accept`
- [ ] SSE `claim_verified` events

**Accept:** adversarial test drops ≥30% ungrounded claims; dedup removes ≥20% dupes on news queries.

## Phase 4 — Synthesizer + SSE Streaming (1 day)

**Goal:** full cited report streams token-by-token.
- [ ] `agents/synthesizer.py`: 120b, input = top-15 verified claims + outline, output markdown with `[1][2][3]`, temp 0.3
- [ ] `routes/research.py`: `EventSourceResponse`, emits `plan → search_progress* → claim_verified* → token* → done`
- [ ] Post-check: every paragraph has citation; else one repair pass
- [ ] Log `latency_ms`, `tokens`, `cost_per_query`

**Accept:** end-to-end p95 <25s free-tier (18s needs paid tier / concurrency 8); sample report has zero uncited paragraphs.

## Phase 5 — Web UI + Hono Gateway (2 days)

**Goal:** Perplexity-clone demo.
- [ ] `web/app/page.tsx`: query box, `lib/sse.ts` reader with reconnect
- [ ] `ReportStream.tsx`: `react-markdown` + `[n]` hover cards
- [ ] `SourcesPanel.tsx`: numbered sources sidebar with favicons
- [ ] `TraceView.tsx`: timeline router→planner→researchers→verifier (from SSE events)
- [ ] `gateway/src/index.ts`: Hono proxy `:3001 → :8000`, rate-limit 10 req/min/IP, CORS

**Accept:** demo flow query→streaming→sources→trace works; mobile readable.

## Phase 6 — Eval Set + Hardening (2 days)

**Goal:** prove `faithfulness 0.84` + `p95 18s`.
- [ ] `evals/tasks.yaml`: 30 tasks (10 factual, 10 comparison, 5 contested, 5 long-tail)
- [ ] `evals/scorer.py`: faithfulness via 20b judge (claim→evidence entailment), citation precision/recall, p50/p95, cost
- [ ] `make eval` → `docs/eval_results.json` + Phoenix dataset
- [ ] Tune: topK, semaphore, verifier threshold until faithfulness ≥0.84
- [ ] `README` hiring-line section + 60s demo script + `docker-compose.yml` (Phoenix only)

**Accept:** `make eval` prints `{faithfulness, citation_p, p50_ms, p95_ms}`; report committed.

---

## 5. Env Template (.env.example)

```
GROQ_API_KEY=gsk_...
GROQ_PLANNER_MODEL=openai/gpt-oss-120b
GROQ_FAST_MODEL=openai/gpt-oss-20b
GROQ_FALLBACK_MODEL=qwen/qwen3-32b
DATABASE_URL=postgresql://user:pass@ep-xxx.neon.tech/signalsift
SEARXNG_URL=https://searx.be
TAVILY_API_KEY=
MAX_CONCURRENT_RESEARCHERS=4
PHOENIX_ENDPOINT=https://app.phoenix.arize.com
```

## 6. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Free-tier 429 on 8-way fan-out | Default 4, semaphore + jitter retry, `MAX_CONCURRENT` flag |
| Public SearXNG flaky | Tavily fallback, cache, timeout 10s |
| Scraping blocked / JS-heavy | trafilatura first, Playwright last, always cap 8k chars |
| GPT-OSS prompting differs from Llama | Model-agnostic prompts, JSON mode + Pydantic validation + parse-retry |
| Cost blowup | Token logging per query, topK caps, eval cost gate |

## 7. What to Run Next

```bash
make dev      # API :8000
make web      # Next.js :3000
make eval     # 30-task scorer
```

Say **"proceed to Phase 0"** and share whether you have `DATABASE_URL` + `GROQ_API_KEY` ready — scaffold will wire them, otherwise it boots with mocks.
