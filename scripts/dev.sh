#!/usr/bin/env bash
# Start both backend (uvicorn) and frontend (Next.js) for local development.
#
# The backend runs on http://localhost:8000 (Swagger at /docs).
# The frontend runs on http://localhost:3000 and rewrites /api to the backend.
#
# Usage:
#   bash scripts/dev.sh                  # starts both
#   bash scripts/dev.sh --backend-only   # backend only
#   bash scripts/dev.sh --frontend-only  # frontend only
#
# Press Ctrl+C to stop both.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BACKEND_ONLY=false
FRONTEND_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --backend-only)  BACKEND_ONLY=true ;;
    --frontend-only) FRONTEND_ONLY=true ;;
  esac
done

cleanup() {
  echo ""
  echo "[dev] Shutting down..."
  kill "$BACKEND_PID" 2>/dev/null || true
  kill "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" 2>/dev/null || true
  wait "$FRONTEND_PID" 2>/dev/null || true
  echo "[dev] Stopped."
}
trap cleanup EXIT INT TERM

# --- Backend ---
if [[ "$FRONTEND_ONLY" == false ]]; then
  echo "[dev] Starting backend..."
  bash "$SCRIPT_DIR/run-backend.sh" &
  BACKEND_PID=$!
  sleep 2
  if kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "[dev] Backend running (PID $BACKEND_PID) on http://localhost:8000"
  else
    echo "[dev] Backend failed to start. Check logs above."
    exit 1
  fi
fi

# --- Frontend ---
if [[ "$BACKEND_ONLY" == false ]]; then
  echo "[dev] Starting frontend..."
  bash "$SCRIPT_DIR/run-frontend.sh" &
  FRONTEND_PID=$!
  sleep 2
  if kill -0 "$FRONTEND_PID" 2>/dev/null; then
    echo "[dev] Frontend running (PID $FRONTEND_PID) on http://localhost:3000"
  else
    echo "[dev] Frontend failed to start. Check logs above."
    exit 1
  fi
fi

echo ""
echo "=========================================="
echo "  RAG Platform — Development"
echo "=========================================="
echo "  Backend:   http://localhost:8000/docs"
echo "  Frontend:  http://localhost:3000"
echo "=========================================="
echo ""
echo "Press Ctrl+C to stop."

# Wait for either to exit
wait
