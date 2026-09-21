<p align="center">
  <img src="apps/web/public/logo.png" alt="SignalSift logo" width="120" />
</p>

<h1 align="center">SignalSift</h1>

<p align="center">A Groq-powered alternative to Perplexity Deep Research.</p>

Ask one hard question. Parallel agents research 10–20 sources, a verifier
rejects ungrounded claims, and you get a streaming cited report. No local
GPU needed — everything runs through the Groq API.

## Run it

```bash
cp .env.example .env   # GROQ_API_KEY, DATABASE_URL (Neon), TAVILY_API_KEY (optional)
make sync              # install Python + JS deps
make dev-all           # API :8000 + gateway :3001 + web UI :3000
```

Open http://127.0.0.1:3000 and ask a question.

## How it works

Router (gpt-oss-20b) → planner (gpt-oss-120b, 5–8 sub-questions) →
LangGraph fan-out → researchers (SearXNG/Tavily search, trafilatura scrape,
claim extraction) → dedup + citation graph → verifier (grounding check + NLI,
max 3 tries) → streaming markdown report with `[1][2][3]` citations.

`apps/api` FastAPI swarm (uv) · `apps/web` Next.js UI (bun) ·
`apps/gateway` Hono proxy (rate-limit + CORS) · Neon Postgres + pgvector ·
Phoenix Cloud tracing.

## Measured

30-task eval set (`apps/api/evals`, `docs/eval_results.json`):

- Faithfulness **0.927** (317 held-out judged claims)
- Citation precision 0.627, supported rate 0.676
- p50 24s / p95 29s on Groq free tier

```bash
make verify   # lint + tests + build + boot + end-to-end check
make eval     # small 3-task eval (cheap on credits)
make down     # stop everything
```
