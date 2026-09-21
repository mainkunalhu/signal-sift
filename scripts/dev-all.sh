#!/usr/bin/env bash
# Boot the full stack IN FOREGROUND with live, prefixed logs — like any dev server.
# Ctrl-C stops everything. Spends nothing (no tests, no builds, no queries).
#
# Why boots were slow: the API preloaded the embedding model on every boot
# (~20s torch load). SKIP_WARMUP=1 (default here) skips it; the first research
# query pays ~15s model load instead, visible in the [api] logs.
# Unset it for production-like boots: SKIP_WARMUP= make dev-all
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export SKIP_WARMUP="${SKIP_WARMUP:-1}"

command -v uv >/dev/null || { echo "missing: uv (brew install uv)"; exit 1; }
command -v bun >/dev/null || { echo "missing: bun (brew install bun)"; exit 1; }

trap 'kill 0 2>/dev/null' EXIT INT TERM

# Health reporter: prints UP lines as each service becomes ready.
(
  up() { echo "[up] $1"; }
  wait_for() {
    local i
    for i in $(seq 1 "$3"); do
      if curl -sf -m 2 "$1" >/dev/null 2>&1; then up "$2"; return 0; fi
      sleep 2
    done
    echo "[up] TIMEOUT: $2 (check the [api]/[gw]/[web] logs above)"
  }
  wait_for "http://127.0.0.1:8000/" "api      http://127.0.0.1:8000 (docs: /docs)" 90
  wait_for "http://127.0.0.1:3001/health" "gateway  http://127.0.0.1:3001" 30
  wait_for "http://127.0.0.1:3000/" "web UI   http://127.0.0.1:3000" 90
  echo "[up] All up. Open the UI and ask a question. Ctrl-C stops everything."
) &

(cd "$ROOT/apps/api" && uv run uvicorn main:app --port 8000 2>&1 | sed -l 's/^/[api] /') &
(cd "$ROOT/apps/gateway" && bun run src/index.ts 2>&1 | sed -l 's/^/[gw] /') &
(cd "$ROOT/apps/web" && bun run dev --port 3000 2>&1 | sed -l 's/^/[web] /') &

wait
