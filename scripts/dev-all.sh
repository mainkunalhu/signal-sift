#!/usr/bin/env bash
# Boot the full stack for manual testing: API + gateway + web.
# Spends NOTHING: no tests, no builds, no queries — just processes + health.
# Usage: make dev-all   |   Stop: make down
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API="$ROOT/apps/api"
WEB="$ROOT/apps/web"
GW="$ROOT/apps/gateway"

command -v uv >/dev/null || { echo "missing: uv (brew install uv)"; exit 1; }
command -v bun >/dev/null || { echo "missing: bun (brew install bun)"; exit 1; }

pkill -f "uvicorn main:app" 2>/dev/null || true
pkill -f "bun run src/index.ts" 2>/dev/null || true
pkill -f "bun run dev" 2>/dev/null || true
sleep 2

(cd "$API" && nohup uv run uvicorn main:app --port 8000 > /tmp/signalsift-api.log 2>&1 &)
(cd "$GW" && nohup bun run src/index.ts > /tmp/signalsift-gw.log 2>&1 &)
(cd "$WEB" && nohup bun run dev --port 3000 > /tmp/signalsift-web.log 2>&1 &)

wait_for() {
  local i
  for i in $(seq 1 "$3"); do
    if curl -sf -m 3 "$1" >/dev/null 2>&1; then echo "  UP: $2"; return 0; fi
    sleep 2
  done
  echo "  DOWN: $2 (see /tmp/signalsift-*.log)"; exit 1
}
wait_for "http://localhost:8000/health" "api      http://localhost:8000 (docs: /docs)" 40
wait_for "http://localhost:3001/health" "gateway  http://localhost:3001" 20
wait_for "http://localhost:3000/" "web UI   http://localhost:3000" 30

echo ""
echo "All up. Open the UI, ask a question, watch it research."
echo "Stop everything: make down"
