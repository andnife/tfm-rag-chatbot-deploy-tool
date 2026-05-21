#!/usr/bin/env bash
# Start the backend (uvicorn) against the locally running docker stack.
#
# Assumes you've already run `scripts/setup.sh` at least once on this machine.
# Reads JWT_SECRET / FERNET_KEY from infra/.env so the values match the
# dockerized services.
#
# Usage:
#   bash scripts/run-backend.sh                       # serves on :8000
#   bash scripts/run-backend.sh --port 9000           # override port
#   bash scripts/run-backend.sh --no-reload           # production-ish (no autoreload)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
ENV_FILE="$REPO_ROOT/infra/.env"

[[ -d "$BACKEND_DIR/.venv" ]] || {
  echo "[err] backend/.venv does not exist. Run scripts/setup.sh first." >&2
  exit 1
}
[[ -f "$ENV_FILE" ]] || {
  echo "[err] infra/.env does not exist. Run scripts/setup.sh first." >&2
  exit 1
}

# shellcheck disable=SC1091
source "$BACKEND_DIR/.venv/bin/activate"

export POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag'
export QDRANT_URL='http://localhost:6333'
export OLLAMA_BASE_URL='http://localhost:11434'
export JWT_SECRET=$(grep '^JWT_SECRET=' "$ENV_FILE" | cut -d= -f2-)
export FERNET_KEY=$(grep '^FERNET_KEY=' "$ENV_FILE" | cut -d= -f2-)
export STORAGE_LOCAL_PATH=${STORAGE_LOCAL_PATH:-/tmp/tfm_rag_storage}
mkdir -p "$STORAGE_LOCAL_PATH"

# Defaults — overridden by argv if the user passed them.
PORT=8000
RELOAD="--reload"
EXTRA=()
while (($#)); do
  case "$1" in
    --port) PORT="$2"; shift 2;;
    --port=*) PORT="${1#*=}"; shift;;
    --no-reload) RELOAD=""; shift;;
    *) EXTRA+=("$1"); shift;;
  esac
done

cd "$BACKEND_DIR"
echo "[run-backend] uvicorn on http://localhost:$PORT — Swagger at /docs"
exec uvicorn tfm_rag.infrastructure.api.app:app \
  --host 0.0.0.0 --port "$PORT" $RELOAD "${EXTRA[@]}"
