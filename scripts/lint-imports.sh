#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  cat <<'USAGE'
Usage: scripts/lint-imports.sh

Runs import-linter against backend/src/tfm_rag to enforce the hexagonal
boundaries (domain independence, application -> infrastructure forbidden,
infrastructure -> application -> domain layering). See backend/pyproject.toml
[tool.importlinter] for the contracts and documented ignore_imports debt.

Exit codes:
  0 — all contracts kept
  1 — a contract is broken
USAGE
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."

cd "$REPO_ROOT/backend"

.venv/bin/lint-imports
