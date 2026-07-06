#!/usr/bin/env bash
# Start the frontend dev server (Next.js) with rewrites to the backend.
#
# Assumes you've already run `scripts/setup.sh` at least once on this machine.
# The Next dev server rewrites /api/* and /widget/* to http://localhost:8000.
#
# NOTE: the Next dev proxy caps upstream requests at ~30s, so the chat
# (LLM on CPU, ~3.5min) will fail through `next dev`. For end-to-end chat
# locally use the prod nginx (infra/docker-compose.prod.yml) which routes
# /api directly to the backend. Short requests (login/lists) work fine here.
#
# Usage:
#   bash scripts/run-frontend.sh                 # serves on :3000
#   bash scripts/run-frontend.sh --port 4000     # override port

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"

[[ -d "$FRONTEND_DIR/node_modules" ]] || {
  echo "[err] frontend/node_modules does not exist. Run scripts/setup.sh first." >&2
  exit 1
}

# Defaults — overridden by argv if the user passed them.
PORT=3000
EXTRA=()
while (($#)); do
  case "$1" in
    --port) PORT="$2"; shift 2;;
    --port=*) PORT="${1#*=}"; shift;;
    *) EXTRA+=("$1"); shift;;
  esac
done

cd "$FRONTEND_DIR"
echo "[run-frontend] Next dev server on http://localhost:$PORT — rewriting /api+/widget to http://localhost:8000"
exec npx next dev -p "$PORT" "${EXTRA[@]}"
