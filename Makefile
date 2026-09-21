dev:
	cd apps/api && uv run uvicorn main:app --reload --port 8000

web:
	cd apps/web && bun run dev

gateway:
	cd apps/gateway && bun run dev

# Small by default: 3 tasks, cheap on API credits.
# Full 30-task run: cd apps/api && uv run python -m evals.scorer --max-subquestions 4
eval:
	cd apps/api && uv run python -m evals.scorer --limit 3 --max-subquestions 2

phoenix:
	@echo "Phoenix is cloud-hosted (no Docker). View traces at https://app.phoenix.arize.com"

sync:
	cd apps/api && uv sync && cd ../web && bun install && cd ../gateway && bun install
