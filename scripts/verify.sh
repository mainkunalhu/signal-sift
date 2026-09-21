#!/usr/bin/env bash
# One command to prove the whole stack works:
#   lint + offline unit tests + web build, then boot API/gateway/web,
#   then a full SSE run through the gateway.
#
# Credit-safe by design: the e2e query is chitchat ("hello there"), which
# short-circuits at the router — 1 cheap Groq call, ZERO Tavily searches.
# For a real research run (spends credits), use: make demo
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API="$ROOT/apps/api"
WEB="$ROOT/apps/web"
GW="$ROOT/apps/gateway"

pass() { echo "  PASS: $1"; }
fail() { echo "  FAIL: $1"; echo "  Logs: /tmp/signalsift-api.log /tmp/signalsift-gw.log /tmp/signalsift-web.log"; exit 1; }

command -v uv >/dev/null || { echo "missing: uv (brew install uv)"; exit 1; }
command -v bun >/dev/null || { echo "missing: bun (brew install bun)"; exit 1; }
command -v curl >/dev/null || { echo "missing: curl"; exit 1; }

echo "== 1. lint + unit tests (offline, zero credits) =="
(cd "$API" && uv run ruff check . >/dev/null 2>&1) && pass "ruff" || fail "ruff"
(cd "$API" && uv run pytest tests/ -q 2>&1 | tail -1)

echo "== 2. web production build =="
(cd "$WEB" && bun run build >/dev/null 2>&1) && pass "next build" || fail "next build"

echo "== 3. boot services =="
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
    if curl -sf -m 3 "$1" >/dev/null 2>&1; then pass "$2"; return 0; fi
    sleep 2
  done
  fail "$2"
}
wait_for "http://127.0.0.1:8000/" "api :8000" 40
wait_for "http://127.0.0.1:3001/health" "gateway :3001" 20
wait_for "http://127.0.0.1:3000/" "web :3000" 30

echo "== 4. e2e SSE through gateway (chitchat: 1 Groq call, 0 Tavily) =="
OUT=$(curl -sN -X POST http://127.0.0.1:3001/api/research \
  -H "Content-Type: application/json" \
  -d '{"query":"hello there","max_subquestions":2}' --max-time 90)
echo "$OUT" | grep -q "not_research" \
  && pass "sse chain browser->gateway->api->done" \
  || fail "sse chain (no not_research in response)"

echo ""
echo "ALL GREEN."
echo "  UI:      http://127.0.0.1:3000"
echo "  API docs http://127.0.0.1:8000/docs  (health: /health)"
echo "  Stop:    make down"
