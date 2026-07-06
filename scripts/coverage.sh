#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  cat <<'USAGE'
Usage: scripts/coverage.sh [--no-html]

Runs pytest with coverage gating on backend/src/tfm_rag/domain,
backend/src/tfm_rag/application and backend/src/tfm_rag/infrastructure.
Fails if combined coverage drops below 79%.

By default writes the HTML report to docs/coverage/. Pass --no-html to skip
HTML generation (useful from the pre-commit hook where rebuilding the report
on every commit would be noisy).

Exit codes:
  0 — coverage gate passed
  1 — coverage gate failed
  2 — pytest crashed for non-coverage reasons
USAGE
  exit 0
fi

EMIT_HTML=1
if [[ "${1:-}" == "--no-html" ]]; then
  EMIT_HTML=0
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."

REPORT_FLAGS=("--cov-report=term")
if [[ "$EMIT_HTML" == "1" ]]; then
  REPORT_FLAGS+=("--cov-report=html:${REPO_ROOT}/docs/coverage")
fi

cd "$REPO_ROOT/backend"

# Scope: unit tests only. Integration tests depend on Docker services
# (postgres, qdrant, ollama, mysql) and are not appropriate for a pre-commit
# gate that must run on a clean developer machine.
.venv/bin/pytest -q tests/unit \
  --cov=src/tfm_rag/domain \
  --cov=src/tfm_rag/application \
  --cov=src/tfm_rag/infrastructure \
  --cov-fail-under=79 \
  "${REPORT_FLAGS[@]}"
