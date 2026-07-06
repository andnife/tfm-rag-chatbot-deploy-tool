#!/usr/bin/env bash
# One-command e2e launcher: ensure the stack is up, then run Playwright.
# The nginx mirror itself is started by Playwright's global-setup.
#
# Usage:
#   bash scripts/e2e.sh                 # all projects
#   bash scripts/e2e.sh --project=fast  # quick, no-LLM specs
#   bash scripts/e2e.sh --project=llm   # chat/ingest/eval/journeys (slow, serial)
#   bash scripts/e2e.sh --list
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Local services must bypass any inherited corporate proxy (WSL injects
# HTTP_PROXY) — otherwise both our curl probes and the backend's httpx clients
# route http://localhost:* through the proxy and time out.
export NO_PROXY="localhost,127.0.0.1,::1,postgres,qdrant,mysql_source,backend${NO_PROXY:+,$NO_PROXY}"
export no_proxy="$NO_PROXY"

log() { echo "[e2e] $*"; }

# 0. Fail loudly if Docker isn't usable (otherwise `set -e` exits silently).
if ! { command -v docker >/dev/null && docker info >/dev/null 2>&1; }; then
  log "ERROR: Docker no está disponible. Arráncalo (Docker Desktop / demonio) y reintenta."
  log "Sugerencia: 'bash scripts/verify.sh --preflight' para un diagnóstico completo."
  exit 1
fi

# 1. Docker services + migrations.
log "levantando servicios docker (postgres, qdrant, mysql)…"
( cd infra && docker compose up -d postgres qdrant mysql_source >/dev/null )
log "aplicando migraciones (alembic upgrade head)…"
( cd backend && set -a; . ../infra/.env; set +a
  export POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag'
  .venv/bin/python -m alembic upgrade head >/dev/null )

# 2. Backend :8000.
if ! curl -sf -o /dev/null --max-time 3 http://localhost:8000/docs; then
  log "starting backend…"
  set -a; . infra/.env; set +a
  setsid nohup env OPENAI_API_KEY="${OPENAI_API_KEY:-}" bash scripts/run-backend.sh --no-reload \
    > /tmp/tfm-backend.log 2>&1 < /dev/null &
  for _ in $(seq 1 30); do curl -sf -o /dev/null --max-time 3 http://localhost:8000/docs && break; sleep 2; done
fi

# 3. Next :3001.
if ! curl -sf -o /dev/null --max-time 3 http://localhost:3001/login; then
  log "starting next on :3001…"
  ( cd frontend && setsid nohup npx next dev -p 3001 -H 0.0.0.0 > /tmp/tfm-next-dev.log 2>&1 < /dev/null & )
  for _ in $(seq 1 40); do curl -sf -o /dev/null --max-time 3 http://localhost:3001/login && break; sleep 2; done
fi

# 4. Playwright (global-setup starts the mirror; baseURL = mirror :8080).
log "running playwright…"
cd e2e
exec env E2E_BASE_URL="${E2E_BASE_URL:-http://localhost:8080}" npx playwright test "$@"
