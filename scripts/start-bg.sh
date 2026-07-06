#!/usr/bin/env bash
# Start infra (docker) + backend (uvicorn) + frontend (Next.js) in background.
#
# Usage:
#   bash scripts/start-bg.sh              # starts all 3 layers
#   bash scripts/start-bg.sh --backend-only   # infra + backend only
#   bash scripts/start-bg.sh --frontend-only  # frontend only (assumes infra+backend running)
#
# Logs go to scripts/logs/{infra,backend,frontend}.log
# Re-running is safe: kills any previous instance before starting fresh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"
INFRA_DIR="$REPO_ROOT/infra"
LOG_DIR="$SCRIPT_DIR/logs"
PID_DIR="$SCRIPT_DIR"

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BLUE=$'\033[34m'; RESET=$'\033[0m'
log()  { printf "%s[start-bg]%s %s\n" "$BLUE"  "$RESET" "$*"; }
ok()   { printf "%s[ ok ]%s %s\n" "$GREEN" "$RESET" "$*"; }
warn() { printf "%s[warn]%s %s\n" "$YELLOW" "$RESET" "$*"; }
err()  { printf "%s[err ]%s %s\n" "$RED"   "$RESET" "$*" >&2; exit 1; }

# --- Flags ---
BACKEND_ONLY=false
FRONTEND_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --backend-only)  BACKEND_ONLY=true ;;
    --frontend-only) FRONTEND_ONLY=true ;;
  esac
done

# --- Stop previous instances if running ---
stop_if_running() {
  local name="$1" pid_file="$2"
  if [[ -f "$pid_file" ]]; then
    local old_pid
    old_pid=$(cat "$pid_file")
    if kill -0 "$old_pid" 2>/dev/null; then
      warn "Stopping previous $name (PID $old_pid)..."
      kill "$old_pid" 2>/dev/null || true
      sleep 1
      kill -0 "$old_pid" 2>/dev/null && kill -9 "$old_pid" 2>/dev/null || true
    fi
    rm -f "$pid_file"
  fi
}

# --- Validate prerequisites ---
mkdir -p "$LOG_DIR"

if [[ "$FRONTEND_ONLY" == false ]]; then
  [[ -d "$BACKEND_DIR/.venv" ]] || err "backend/.venv not found. Run: bash scripts/setup.sh"
  [[ -f "$INFRA_DIR/.env" ]]   || err "infra/.env not found. Run: bash scripts/setup.sh"
  command -v docker >/dev/null 2>&1 || err "docker not found. Install Docker."
fi

if [[ "$BACKEND_ONLY" == false ]]; then
  [[ -d "$FRONTEND_DIR/node_modules" ]] || err "frontend/node_modules not found. Run: cd frontend && npm install"
fi

# ============================
# Layer 1: Docker infra
# ============================
if [[ "$FRONTEND_ONLY" == false ]]; then
  log "Checking infra services..."

  # Check if postgres is accepting connections on port 5432
  INFRA_NEEDED=false
  if ! nc -z localhost 5432 2>/dev/null; then
    INFRA_NEEDED=true
    warn "Postgres not reachable on :5432"
  fi
  if ! nc -z localhost 6333 2>/dev/null; then
    INFRA_NEEDED=true
    warn "Qdrant not reachable on :6333"
  fi

  if [[ "$INFRA_NEEDED" == true ]]; then
    log "Starting docker-compose services (postgres, qdrant, ollama)..."
    cd "$INFRA_DIR"
    docker compose up -d postgres qdrant ollama 2>&1 | tail -5

    log "Waiting for postgres + qdrant to be healthy..."
    DEADLINE=$((SECONDS + 120))
    while (( SECONDS < DEADLINE )); do
      PG_OK=false; QD_OK=false
      nc -z localhost 5432 2>/dev/null && PG_OK=true
      nc -z localhost 6333 2>/dev/null && QD_OK=true
      if [[ "$PG_OK" == true && "$QD_OK" == true ]]; then
        break
      fi
      printf "."
      sleep 2
    done
    echo

    if [[ "$PG_OK" == true && "$QD_OK" == true ]]; then
      ok "Infra services ready"
    else
      err "Infra services did not come up in 120s. Check: cd infra && docker compose logs"
    fi

    # Run alembic migrations
    log "Applying alembic migrations..."
    cd "$BACKEND_DIR"
    # shellcheck disable=SC1091
    source "$BACKEND_DIR/.venv/bin/activate"
    export POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag'
    export JWT_SECRET=$(grep '^JWT_SECRET=' "$INFRA_DIR/.env" | cut -d= -f2-)
    export FERNET_KEY=$(grep '^FERNET_KEY=' "$INFRA_DIR/.env" | cut -d= -f2-)
    alembic upgrade head 2>&1 | tail -3
    deactivate 2>/dev/null || true
    ok "Migrations applied"
  else
    ok "Infra services already running"
  fi
fi

# ============================
# Layer 2: Backend
# ============================
if [[ "$FRONTEND_ONLY" == false ]]; then
  stop_if_running "backend" "$PID_DIR/backend.pid"

  log "Starting backend..."
  # shellcheck disable=SC1091
  source "$BACKEND_DIR/.venv/bin/activate"

  export POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag'
  export QDRANT_URL='http://localhost:6333'
  export OLLAMA_BASE_URL='http://localhost:11434'
  export JWT_SECRET=$(grep '^JWT_SECRET=' "$INFRA_DIR/.env" | cut -d= -f2-)
  export FERNET_KEY=$(grep '^FERNET_KEY=' "$INFRA_DIR/.env" | cut -d= -f2-)
  export STORAGE_LOCAL_PATH=${STORAGE_LOCAL_PATH:-/tmp/tfm_rag_storage}
  mkdir -p "$STORAGE_LOCAL_PATH"

  cd "$BACKEND_DIR"
  # --loop asyncio (not uvloop): RAGAS uses nest_asyncio, which cannot patch
  # uvloop and crashes the worker on import (eval router imports ragas).
  nohup uvicorn tfm_rag.infrastructure.api.app:app \
    --host 0.0.0.0 --port 8000 --loop asyncio --reload \
    > "$LOG_DIR/backend.log" 2>&1 &
  BACKEND_PID=$!
  echo "$BACKEND_PID" > "$PID_DIR/backend.pid"
  deactivate 2>/dev/null || true

  sleep 2
  if kill -0 "$BACKEND_PID" 2>/dev/null; then
    ok "Backend running (PID $BACKEND_PID) — http://localhost:8000/docs"
  else
    err "Backend failed to start. Check: tail $LOG_DIR/backend.log"
  fi
fi

# ============================
# Layer 3: Frontend
# ============================
if [[ "$BACKEND_ONLY" == false ]]; then
  stop_if_running "frontend" "$PID_DIR/frontend.pid"

  log "Starting frontend..."
  cd "$FRONTEND_DIR"
  nohup npx next dev -p 3000 \
    > "$LOG_DIR/frontend.log" 2>&1 &
  FRONTEND_PID=$!
  echo "$FRONTEND_PID" > "$PID_DIR/frontend.pid"

  sleep 3
  if kill -0 "$FRONTEND_PID" 2>/dev/null; then
    ok "Frontend running (PID $FRONTEND_PID) — http://localhost:3000"
  else
    err "Frontend failed to start. Check: tail $LOG_DIR/frontend.log"
  fi
fi

# --- Summary ---
echo ""
echo "=========================================="
echo "  RAG Platform — Background Services"
echo "=========================================="
if [[ "$FRONTEND_ONLY" == false ]]; then
  echo "  Backend:   http://localhost:8000/docs  (PID $BACKEND_PID)"
fi
if [[ "$BACKEND_ONLY" == false ]]; then
  echo "  Frontend:  http://localhost:3000        (PID $FRONTEND_PID)"
fi
echo "=========================================="
echo ""
echo "  Logs:"
if [[ "$FRONTEND_ONLY" == false ]]; then
  echo "    tail -f $LOG_DIR/backend.log"
fi
if [[ "$BACKEND_ONLY" == false ]]; then
  echo "    tail -f $LOG_DIR/frontend.log"
fi
echo ""
echo "  Stop all:  bash scripts/stop-bg.sh"
echo "  Stop one:  bash scripts/stop-bg.sh --backend-only"
echo "             bash scripts/stop-bg.sh --frontend-only"
echo ""
