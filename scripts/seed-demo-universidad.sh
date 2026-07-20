#!/usr/bin/env bash
# seed-demo-universidad.sh — Provision the "Universidad Europea" demo account.
#
# Purpose: a clean, dedicated, RE-RUNNABLE demo tenant for the TFM defense.
# Creates (or reuses, by name) under a fresh user:
#   1. User demo@fake.com (register, or login fallback)
#   2. A DeepInfra credential — COPIED from an existing working credential via
#      the DB, so no plaintext API key is needed (same Fernet key = valid).
#   3. Knowledge Base "Universidad Europea" with the 4 curated docs ingested
#      (embeddings via Ollama bge-m3).
#   4. Chatbot "Asistente Universidad Europea" wired to that KB and pointed at
#      DeepInfra (Qwen2.5-72B by default), abstention on, temperature 0.3.
#
# Idempotent: re-running reuses the user, the DeepInfra credential, and a KB /
# bot with the same name if they already exist (so it won't pile up dupes).
#
# Usage:
#   bash scripts/seed-demo-universidad.sh
#   bash scripts/seed-demo-universidad.sh --email demo@fake.com --password Demo1234
#   bash scripts/seed-demo-universidad.sh --model meta-llama/Meta-Llama-3.1-8B-Instruct
#
# Requires: curl, jq, backend on :8000, Ollama on :11434 with bge-m3,
#           Postgres container running, and an existing DeepInfra credential to copy.

set -euo pipefail

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BLUE=$'\033[34m'; RESET=$'\033[0m'
log()  { printf "%s[demo]%s %s\n" "$BLUE"  "$RESET" "$*"; }
ok()   { printf "%s[ ok ]%s %s\n" "$GREEN" "$RESET" "$*"; }
warn() { printf "%s[warn]%s %s\n" "$YELLOW" "$RESET" "$*"; }
err()  { printf "%s[err ]%s %s\n" "$RED"   "$RESET" "$*" >&2; exit 1; }

# --- Args / defaults ---
EMAIL="demo@fake.com"
PASSWORD="Demo1234"
MODEL_ID="Qwen/Qwen2.5-72B-Instruct"   # DeepInfra model id for generation
FRONT_PORT="3001"
while (($#)); do
  case "$1" in
    --email)      EMAIL="$2"; shift 2;;
    --email=*)    EMAIL="${1#*=}"; shift;;
    --password)   PASSWORD="$2"; shift 2;;
    --password=*) PASSWORD="${1#*=}"; shift;;
    --model)      MODEL_ID="$2"; shift 2;;
    --model=*)    MODEL_ID="${1#*=}"; shift;;
    --port)       FRONT_PORT="$2"; shift 2;;
    *) shift;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BASE=http://localhost:8000
DOCS_DIR="$REPO_ROOT/docs/demo-knowledge-bases/universidad-europea"
PG_CONTAINER="tfm-rag-postgres-1"
KB_NAME="Universidad Europea"
BOT_NAME="Asistente Universidad Europea"
EMBED_MODEL="bge-m3"; EMBED_DIM=1024

BOT_PROMPT="Eres el asistente virtual de la Universidad Europea. Respondes en español de forma clara y concisa, usando ÚNICAMENTE la información de los documentos de la base de conocimiento. Si la información no está en los documentos, indícalo honestamente y sugiere contactar con el equipo de admisiones, en lugar de inventar datos."

pg() { docker exec -i "$PG_CONTAINER" psql -U tfm -d tfm_rag -tA -c "$1"; }

# --- Preflight ---
command -v curl >/dev/null || err "curl not found"
command -v jq   >/dev/null || err "jq not found"
curl -sf "$BASE/health" >/dev/null 2>&1 || err "Backend not reachable at $BASE — run: bash scripts/start-bg.sh"
[[ -d "$DOCS_DIR" ]] || err "Docs dir not found: $DOCS_DIR"
docker ps --format '{{.Names}}' | grep -q "$PG_CONTAINER" || err "$PG_CONTAINER not running"
curl -sf http://localhost:11434/api/tags 2>/dev/null | jq -e '.models[] | select(.name|startswith("bge-m3"))' >/dev/null \
  || err "Ollama has no bge-m3 model on :11434"

# --- 1. Register or login ---
log "Authenticating $EMAIL..."
AUTH=$(curl -s -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
if ! echo "$AUTH" | jq -e .access_token >/dev/null 2>&1; then
  log "  → user does not exist, registering..."
  AUTH=$(curl -sf -X POST "$BASE/api/auth/register" -H 'Content-Type: application/json' \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}") || err "Register failed"
fi
TOKEN=$(echo "$AUTH" | jq -r .access_token)
TENANT_ID=$(echo "$AUTH" | jq -r '.tenant_id // empty')
AUTH_HDR="Authorization: Bearer $TOKEN"
[[ -n "$TOKEN" && "$TOKEN" != "null" ]] || err "No token acquired"
[[ -n "$TENANT_ID" ]] || TENANT_ID=$(pg "SELECT tenant_id FROM users WHERE email='$EMAIL';")
ok "Authenticated (tenant: $TENANT_ID)"

# --- 2. Ollama credential (auto-created on register) ---
OLLAMA_CRED=$(curl -sf -H "$AUTH_HDR" "$BASE/api/credentials" | jq -r '[.[]|select(.provider_id=="ollama")][0].id')
[[ -n "$OLLAMA_CRED" && "$OLLAMA_CRED" != "null" ]] || err "No Ollama credential on the tenant"
ok "Ollama credential: $OLLAMA_CRED"

# --- 3. DeepInfra credential: reuse if present, else copy from an existing one ---
DEEPINFRA_CRED=$(curl -sf -H "$AUTH_HDR" "$BASE/api/credentials" \
  | jq -r '[.[]|select(.provider_id=="openai_compat" and (.base_url//""|test("deepinfra")))][0].id // empty')
if [[ -n "$DEEPINFRA_CRED" ]]; then
  ok "DeepInfra credential already present: $DEEPINFRA_CRED"
else
  log "Copying an existing DeepInfra credential into this tenant..."
  SRC_CRED=$(pg "SELECT id FROM provider_credentials WHERE provider_id='openai_compat' AND base_url LIKE '%deepinfra%' AND tenant_id <> '$TENANT_ID' LIMIT 1;")
  [[ -n "$SRC_CRED" ]] || err "No source DeepInfra credential found in any tenant to copy from. Create one in the UI first (Settings → Credentials)."
  DEEPINFRA_CRED=$(pg "INSERT INTO provider_credentials
      (id, tenant_id, provider_id, label, api_key_encrypted, base_url, config_source, max_concurrency, min_request_interval_seconds, created_at, updated_at)
    SELECT gen_random_uuid(), '$TENANT_ID', provider_id, 'deepinfra', api_key_encrypted, base_url, config_source, max_concurrency, min_request_interval_seconds, now(), now()
    FROM provider_credentials WHERE id='$SRC_CRED'
    RETURNING id;")
  [[ -n "$DEEPINFRA_CRED" ]] || err "Credential copy failed"
  ok "DeepInfra credential copied: $DEEPINFRA_CRED"
fi

# --- 4. Knowledge Base: reuse by name, else create ---
KB_ID=$(curl -sf -H "$AUTH_HDR" "$BASE/api/knowledge-bases" \
  | jq -r --arg n "$KB_NAME" '[.[]|select(.name==$n)][0].id // empty')
if [[ -n "$KB_ID" ]]; then
  ok "KB already exists: $KB_ID ($KB_NAME) — reusing"
else
  log "Creating KB \"$KB_NAME\"..."
  KB=$(curl -sf -X POST "$BASE/api/knowledge-bases" -H "$AUTH_HDR" -H 'Content-Type: application/json' -d "{
    \"name\": \"$KB_NAME\",
    \"description\": \"Base de conocimiento de demo: información institucional, oferta académica, admisiones/precios/becas y vida universitaria.\",
    \"chunking_config\": {\"strategy\": \"fixed\", \"chunk_size\": 600, \"chunk_overlap\": 100},
    \"embedding_selection\": {\"provider_id\":\"ollama\",\"credential_id\":\"$OLLAMA_CRED\",\"model_id\":\"$EMBED_MODEL\",\"dim\":$EMBED_DIM}
  }")
  KB_ID=$(echo "$KB" | jq -r .id)
  [[ -n "$KB_ID" && "$KB_ID" != "null" ]] || err "KB creation failed: $KB"
  ok "KB created: $KB_ID"

  # --- 5. Upload the 4 curated docs (as .txt/text-plain) and wait for ingestion ---
  log "Uploading curated documents..."
  TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
  for md in "$DOCS_DIR"/0[1-4]-*.md; do
    cp "$md" "$TMP/$(basename "${md%.md}").txt"
  done
  for f in "$TMP"/*.txt; do
    RESP=$(curl -sf -X POST "$BASE/api/knowledge-bases/$KB_ID/sources/documents" \
      -H "$AUTH_HDR" -F "file=@$f;type=text/plain")
    JOB_ID=$(echo "$RESP" | jq -r .job_id)
    log "  $(basename "$f") → job $JOB_ID"
    for i in $(seq 1 90); do
      STATE=$(curl -sf -H "$AUTH_HDR" "$BASE/api/ingestion-jobs/$JOB_ID" | jq -r .status)
      [[ "$STATE" == "done" ]]   && { ok "  $(basename "$f") ingestado"; break; }
      [[ "$STATE" == "failed" ]] && err "  $(basename "$f") ingestion FAILED: $(curl -sf -H "$AUTH_HDR" "$BASE/api/ingestion-jobs/$JOB_ID" | jq -r '.error//"?"')"
      printf "."; sleep 2
    done
  done
  echo
fi

# --- 6. Chatbot: reuse by name, else create ---
BOT_ID=$(curl -sf -H "$AUTH_HDR" "$BASE/api/chatbots" \
  | jq -r --arg n "$BOT_NAME" '[.[]|select(.name==$n)][0].id // empty')
if [[ -n "$BOT_ID" ]]; then
  ok "Chatbot already exists: $BOT_ID ($BOT_NAME) — reusing"
else
  log "Creating chatbot \"$BOT_NAME\" (DeepInfra: $MODEL_ID)..."
  BOT=$(curl -s -X POST "$BASE/api/chatbots" -H "$AUTH_HDR" -H 'Content-Type: application/json' -d "{
    \"name\": \"$BOT_NAME\",
    \"description\": \"Asistente de demo sobre la Universidad Europea (RAG documental).\",
    \"system_prompt\": \"$BOT_PROMPT\",
    \"llm_selection\": {\"provider_id\":\"openai_compat\",\"credential_id\":\"$DEEPINFRA_CRED\",\"model_id\":\"$MODEL_ID\"},
    \"kb_ids\": [\"$KB_ID\"],
    \"pipeline_config\": {
      \"top_k\": 5,
      \"score_threshold\": 0.3,
      \"enable_reranker\": false,
      \"reranker_initial_top_k\": 30,
      \"abstain_when_insufficient\": true,
      \"max_self_correction_retries\": 1,
      \"generation\": {\"top_p\": 1.0, \"max_tokens\": 1024, \"temperature\": 0.3}
    }
  }")
  BOT_ID=$(echo "$BOT" | jq -r .id)
  [[ -n "$BOT_ID" && "$BOT_ID" != "null" ]] || err "Chatbot creation failed: $BOT"
  PUBLIC_KEY=$(echo "$BOT" | jq -r .public_key)
  ok "Chatbot created: $BOT_ID (public_key: ${PUBLIC_KEY:0:16}…)"
fi

# --- 7. Summary ---
cat <<EOF

${GREEN}========================================================================${RESET}
${GREEN}  Cuenta demo lista.${RESET}

  Usuario:   $EMAIL  /  $PASSWORD
  Tenant:    $TENANT_ID
  KB:        $KB_ID  ($KB_NAME)
  Chatbot:   $BOT_ID  ($BOT_NAME)
  Modelo:    DeepInfra $MODEL_ID
  Embedding: $EMBED_MODEL ($EMBED_DIM d, Ollama)

  Frontend (puerto $FRONT_PORT):
    http://localhost:$FRONT_PORT/login                          ← $EMAIL / $PASSWORD
    http://localhost:$FRONT_PORT/knowledge/$KB_ID
    http://localhost:$FRONT_PORT/chatbots/$BOT_ID/playground
${GREEN}========================================================================${RESET}
EOF
