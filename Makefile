dev:
	cd apps/api && uv run uvicorn main:app --reload --port 8000

web:
	cd apps/web && bun run dev

gateway:
	cd apps/gateway && bun run dev

# Boot everything for manual testing: API + gateway + web UI.
# Spends nothing (no tests, no queries). Then open http://localhost:3000.
dev-all:
	bash scripts/dev-all.sh

# Small by default: 3 tasks, cheap on API credits.
# Full 30-task run: cd apps/api && uv run python -m evals.scorer --max-subquestions 4
eval:
	cd apps/api && uv run python -m evals.scorer --limit 3 --max-subquestions 2

# One command: lint + tests + build, boot all services, e2e SSE check.
# Credit-safe (chitchat query: 1 Groq call, 0 Tavily). Leaves servers running.
verify:
	bash scripts/verify.sh

down:
	pkill -f "uvicorn main:app"; pkill -f "bun run src/index.ts"; pkill -f "bun run dev"; echo "stopped"

# Real research demo (SPENDS credits: ~1 query + Tavily searches). Small by default.
demo:
	@echo "WARNING: spends Groq + Tavily credits. Ctrl-C now to abort." && sleep 3 && curl -sN -X POST http://localhost:3001/api/research -H "Content-Type: application/json" -d '{"query": "How do small teams choose between pgvector and Qdrant in 2026?", "max_subquestions": 2}' | grep "^event: " | sort | uniq -c

phoenix:
	@echo "Phoenix is cloud-hosted (no Docker). View traces at https://app.phoenix.arize.com"

sync:
	cd apps/api && uv sync && cd ../web && bun install && cd ../gateway && bun install
