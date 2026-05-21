#!/usr/bin/env bash
# Bootstrap the TFM RAG project on a fresh machine.
#
# What this does (idempotent — safe to re-run):
#   1. Verifies prerequisites: python3.12, docker, docker compose plugin.
#   2. Creates the backend virtualenv at backend/.venv and installs deps.
#   3. Generates infra/.env from infra/.env.example with random JWT_SECRET +
#      FERNET_KEY, dev-friendly STORAGE_LOCAL_PATH, and localhost POSTGRES_URL.
#   4. Pulls + starts the docker-compose services (postgres, qdrant, ollama)
#      and waits until they are healthy.
#   5. Applies alembic migrations against the running Postgres.
#   6. Runs the unit test suite as a smoke check.
#
# What this does NOT do:
#   - Start uvicorn (use `scripts/run-backend.sh` for that, or run uvicorn
#     manually — see backend/README.md).
#   - Install the frontend (there isn't one yet).
#
# Usage:
#   bash scripts/setup.sh
#
# Re-running is safe: dependencies that are already installed are skipped,
# secrets are only generated if missing, migrations are no-op if up to date.

set -euo pipefail

# ---------- helpers ----------

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BLUE=$'\033[34m'; RESET=$'\033[0m'
log()  { printf "%s[setup]%s %s\n" "$BLUE"  "$RESET" "$*"; }
ok()   { printf "%s[ ok ]%s %s\n" "$GREEN" "$RESET" "$*"; }
warn() { printf "%s[warn]%s %s\n" "$YELLOW" "$RESET" "$*"; }
err()  { printf "%s[err ]%s %s\n" "$RED"   "$RESET" "$*"; exit 1; }

# Resolve repo root from this script's location, so it works from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
INFRA_DIR="$REPO_ROOT/infra"
VENV_DIR="$BACKEND_DIR/.venv"

# ---------- 1. Prerequisites ----------

log "Checking prerequisites…"

# Find a Python 3.12. Some distros ship `python3.12`, others ship only `python3`
# whose version happens to be 3.12. Accept either as long as the version is ok.
PYTHON_BIN=""
for candidate in python3.12 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    ver=$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    if [[ "$ver" == "3.12" ]]; then
      PYTHON_BIN="$candidate"
      break
    fi
  fi
done
[[ -n "$PYTHON_BIN" ]] || err "Need Python 3.12. Install it (e.g. \`apt install python3.12 python3.12-venv\` on Ubuntu, \`brew install python@3.12\` on macOS) and re-run."
ok "Python 3.12 found at $(command -v "$PYTHON_BIN")"

command -v docker >/dev/null 2>&1 || err "Docker not found. Install Docker Desktop (or the engine) and re-run."
ok "docker: $(docker --version)"

docker compose version >/dev/null 2>&1 || err "Docker compose plugin not found. Install \`docker-compose-plugin\` (or update Docker Desktop) and re-run."
ok "docker compose: $(docker compose version | head -1)"

# WSL2 sanity check — non-fatal but helpful
if grep -qi microsoft /proc/version 2>/dev/null; then
  if ! docker info >/dev/null 2>&1; then
    err "WSL2 detected but \`docker info\` failed. Enable WSL integration in Docker Desktop → Settings → Resources → WSL Integration."
  fi
  ok "WSL2 docker integration looks live"
fi

# ---------- 2. Backend venv + deps ----------

log "Setting up backend virtualenv…"

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  ok "Created $VENV_DIR"
else
  ok "Virtualenv already exists at $VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

log "Upgrading pip + installing backend deps (this can take a minute on a fresh install)…"
pip install --quiet --upgrade pip
pip install --quiet -e "$BACKEND_DIR[dev]"
ok "Backend deps installed"

# ---------- 3. infra/.env ----------

log "Preparing infra/.env…"

if [[ ! -f "$INFRA_DIR/.env" ]]; then
  cp "$INFRA_DIR/.env.example" "$INFRA_DIR/.env"
  ok "Copied infra/.env from .env.example"
fi

# Replace placeholder secrets if they're still the defaults.
JWT_SECRET=$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_urlsafe(32))')
FERNET_KEY=$("$PYTHON_BIN" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')

# Use a tmp file + mv to be safe on both sed-GNU and sed-BSD.
ENV_FILE="$INFRA_DIR/.env"
tmp=$(mktemp)
while IFS= read -r line || [[ -n "$line" ]]; do
  case "$line" in
    JWT_SECRET=replace_with_*)
      echo "JWT_SECRET=$JWT_SECRET" >> "$tmp"
      ;;
    FERNET_KEY=replace_with_*)
      echo "FERNET_KEY=$FERNET_KEY" >> "$tmp"
      ;;
    STORAGE_LOCAL_PATH=/data/storage)
      # /data/storage requires root; default to /tmp for local dev.
      echo "STORAGE_LOCAL_PATH=/tmp/tfm_rag_storage" >> "$tmp"
      ;;
    *)
      echo "$line" >> "$tmp"
      ;;
  esac
done < "$ENV_FILE"
mv "$tmp" "$ENV_FILE"

# Also surface a local-development POSTGRES_URL. The default in .env.example
# points to the docker hostname `postgres`, which only resolves inside the
# compose network. For uvicorn outside docker we need `localhost`.
if grep -q '^POSTGRES_URL=postgresql+asyncpg://tfm:tfm@postgres:5432' "$ENV_FILE"; then
  warn "POSTGRES_URL in infra/.env points to docker hostname \`postgres\`."
  warn "  → fine for the dockerized backend service."
  warn "  → if you run uvicorn locally, export POSTGRES_URL=postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag in your shell."
fi

ok "infra/.env is ready"

# ---------- 4. Docker compose up ----------

log "Starting docker-compose services (postgres, qdrant, ollama)…"
cd "$INFRA_DIR"
docker compose up -d postgres qdrant ollama

log "Waiting for services to report healthy…"
DEADLINE=$((SECONDS + 180))  # 3 minutes — Ollama first-run pulls models (~5GB)
while (( SECONDS < DEADLINE )); do
  pg_state=$(docker compose ps --format json postgres 2>/dev/null | "$PYTHON_BIN" -c 'import sys,json; d=json.loads(sys.stdin.read() or "{}"); print(d.get("Health") or d.get("State",""))' || echo "")
  qd_state=$(docker compose ps --format json qdrant   2>/dev/null | "$PYTHON_BIN" -c 'import sys,json; d=json.loads(sys.stdin.read() or "{}"); print(d.get("Health") or d.get("State",""))' || echo "")
  ol_state=$(docker compose ps --format json ollama   2>/dev/null | "$PYTHON_BIN" -c 'import sys,json; d=json.loads(sys.stdin.read() or "{}"); print(d.get("Health") or d.get("State",""))' || echo "")
  if [[ "$pg_state" == "healthy" && "$qd_state" == "healthy" ]]; then
    ok "postgres: $pg_state | qdrant: $qd_state | ollama: $ol_state"
    if [[ "$ol_state" != "healthy" ]]; then
      warn "Ollama still pulling models. Migrations + tests below do NOT need Ollama; you can use the API as soon as it goes healthy (\`docker compose ps\`)."
    fi
    break
  fi
  printf "."
  sleep 3
done
echo
(( SECONDS < DEADLINE )) || err "Services did not go healthy within 3 minutes. Check \`docker compose logs\` in $INFRA_DIR."

# ---------- 5. Alembic ----------

log "Applying alembic migrations…"
cd "$BACKEND_DIR"

# Local-dev env: localhost (not docker hostname) for the host's alembic runner.
export POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag'
export QDRANT_URL='http://localhost:6333'
export OLLAMA_BASE_URL='http://localhost:11434'

# JWT_SECRET / FERNET_KEY: read from the just-written .env so the same values
# the dockerized backend will use are also what alembic + tests see.
export JWT_SECRET=$(grep '^JWT_SECRET=' "$ENV_FILE" | cut -d= -f2-)
export FERNET_KEY=$(grep '^FERNET_KEY=' "$ENV_FILE" | cut -d= -f2-)
export STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage'

mkdir -p "$STORAGE_LOCAL_PATH"

alembic upgrade head
ok "Migrations applied. Current heads:"
alembic heads

# ---------- 6. Smoke test ----------

log "Running unit test suite as a smoke check…"
pytest tests/ -m "not integration" -q
ok "Unit tests passed"

# ---------- Done ----------

cat <<EOF

${GREEN}========================================================================${RESET}
${GREEN}  Setup complete.${RESET}

  Next steps:

  • Start the API (run in a separate terminal):
      cd $BACKEND_DIR
      source .venv/bin/activate
      export POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag'
      export QDRANT_URL='http://localhost:6333'
      export OLLAMA_BASE_URL='http://localhost:11434'
      export JWT_SECRET='$JWT_SECRET'
      export FERNET_KEY='$FERNET_KEY'
      export STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage'
      uvicorn tfm_rag.infrastructure.api.app:app --reload --port 8000

  • Open Swagger UI:  http://localhost:8000/docs
  • Or use:           scripts/run-backend.sh   (does the above for you)

  • Frontend: not implemented yet (no plan written). Use the API directly.

  • Integration tests (require Docker stack up — which it is):
      pytest tests/integration -m integration -v

${GREEN}========================================================================${RESET}
EOF
