#!/usr/bin/env bash
# Stop background backend + frontend processes.
#
# Usage:
#   bash scripts/stop-bg.sh              # stops both
#   bash scripts/stop-bg.sh --backend-only
#   bash scripts/stop-bg.sh --frontend-only

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="$SCRIPT_DIR"

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BLUE=$'\033[34m'; RESET=$'\033[0m'
log()  { printf "%s[stop-bg]%s %s\n" "$BLUE"  "$RESET" "$*"; }
ok()   { printf "%s[ ok ]%s %s\n" "$GREEN" "$RESET" "$*"; }
warn() { printf "%s[warn]%s %s\n" "$YELLOW" "$RESET" "$*"; }

BACKEND_ONLY=false
FRONTEND_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --backend-only)  BACKEND_ONLY=true ;;
    --frontend-only) FRONTEND_ONLY=true ;;
  esac
done

stop_service() {
  local name="$1" pid_file="$2"
  if [[ ! -f "$pid_file" ]]; then
    warn "$name: no PID file found"
    return
  fi
  local pid
  pid=$(cat "$pid_file")
  if kill -0 "$pid" 2>/dev/null; then
    log "Stopping $name (PID $pid)..."
    kill "$pid" 2>/dev/null || true
    sleep 1
    # Force kill if still alive
    if kill -0 "$pid" 2>/dev/null; then
      warn "$name didn't stop gracefully, sending SIGKILL..."
      kill -9 "$pid" 2>/dev/null || true
    fi
    ok "$name stopped"
  else
    warn "$name (PID $pid) was not running"
  fi
  rm -f "$pid_file"
}

if [[ "$FRONTEND_ONLY" == false ]]; then
  stop_service "backend" "$PID_DIR/backend.pid"
fi

if [[ "$BACKEND_ONLY" == false ]]; then
  stop_service "frontend" "$PID_DIR/frontend.pid"
fi

echo ""
ok "All services stopped."
