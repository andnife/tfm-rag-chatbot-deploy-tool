#!/usr/bin/env bash
# init-debug.sh — Initialize the system end-to-end for debugging/demos.
#
# Idempotent: re-running just reuses the existing user (login fallback).
# It does NOT delete existing KBs/chatbots — it always creates new ones, so
# /inspect will gradually accumulate them across runs. If you want a clean
# slate, drop the database first:
#
#   cd infra && docker compose down -v && bash ../scripts/setup.sh
#
# What it does:
#   1. Login or register the debug user
#   2. Pick the best Ollama embedding + LLM models actually pulled
#   3. Create a Knowledge Base
#   4. Upload sample documents and wait for ingestion
#   5. Seed the MySQL container with a small customers table
#   6. Attach that MySQL database as a SQL source on the KB
#   7. Create a Chatbot wired to the KB
#   8. Send a test chat
#   9. Print all IDs + helpful URLs
#
# Usage:
#   bash scripts/init-debug.sh
#   bash scripts/init-debug.sh --email foo@bar.com --password secret123
#
# Requires: curl, jq, backend running on :8000, Ollama on :11434,
#           Postgres + MySQL containers running.

set -euo pipefail

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BLUE=$'\033[34m'; RESET=$'\033[0m'
log()  { printf "%s[init]%s %s\n" "$BLUE"  "$RESET" "$*"; }
ok()   { printf "%s[ ok ]%s %s\n" "$GREEN" "$RESET" "$*"; }
warn() { printf "%s[warn]%s %s\n" "$YELLOW" "$RESET" "$*"; }
err()  { printf "%s[err ]%s %s\n" "$RED"   "$RESET" "$*" >&2; exit 1; }

# --- Args ---
EMAIL="debug@test.com"
PASSWORD="debug1234"
SQUAD=""   # --squad: seed the SQuAD doc_only eval KB instead of the demo seed
while (($#)); do
  case "$1" in
    --email)    EMAIL="$2"; shift 2;;
    --email=*)  EMAIL="${1#*=}"; shift;;
    --password) PASSWORD="$2"; shift 2;;
    --password=*) PASSWORD="${1#*=}"; shift;;
    --squad)    SQUAD=1; shift;;
    *) shift;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

BASE=http://localhost:8000
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_DB=tfm_rag_source_test
MYSQL_USER=tfm
MYSQL_PASSWORD=tfm
MYSQL_CONTAINER=tfm-rag-mysql_source-1

# --- Preflight ---
command -v curl >/dev/null || err "curl not found"
command -v jq   >/dev/null || err "jq not found"
curl -sf "$BASE/health" >/dev/null 2>&1 || err "Backend not reachable at $BASE — start it: bash scripts/run-backend.sh"
# MySQL is only needed for the demo seed; --squad is doc_only so it's optional there.
if [[ -z "$SQUAD" ]]; then
  docker ps --format '{{.Names}}' | grep -q "$MYSQL_CONTAINER" || err "$MYSQL_CONTAINER not running — start the stack: cd infra && docker compose up -d"
fi

# --- 1. Login or register ---
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
ok "Token acquired (tenant: $TENANT_ID)"

# --- 2. Pick available Ollama models ---
log "Detecting available Ollama models..."
MODELS=$(curl -sf http://localhost:11434/api/tags 2>/dev/null | jq -r '.models[].name' || echo "")
EMBED_MODEL=""; EMBED_DIM=0
for try in "bge-m3 1024" "nomic-embed-text 768"; do
  m=${try% *}; d=${try#* }
  if echo "$MODELS" | grep -q "^$m"; then EMBED_MODEL=$m; EMBED_DIM=$d; break; fi
done
[[ -n "$EMBED_MODEL" ]] || err "No embedding model available. Run: ollama pull bge-m3"
ok "Embedding: $EMBED_MODEL ($EMBED_DIM d)"

LLM_MODEL=""
for cand in llama3.1 mistral gemma3:1b; do
  if echo "$MODELS" | grep -q "^$cand"; then LLM_MODEL=$cand; break; fi
done
[[ -n "$LLM_MODEL" ]] || err "No LLM model available. Run: ollama pull llama3.1"
ok "LLM: $LLM_MODEL"

# --- 3. Ollama credential ---
log "Fetching Ollama credential..."
CRED_ID=$(curl -sf -H "$AUTH_HDR" "$BASE/api/credentials" \
  | jq -r '[.[] | select(.provider_id=="ollama")][0].id')
[[ -n "$CRED_ID" && "$CRED_ID" != "null" ]] || err "No Ollama credential — was the tenant bootstrap skipped?"
ok "Credential: $CRED_ID"

# --- 4. Create KB ---
log "Creating Knowledge Base..."
TIMESTAMP=$(date +%H%M%S)
if [[ -n "$SQUAD" ]]; then
  KB_NAME="SQuAD KB $TIMESTAMP"
  KB_DESC="KB doc_only para eval (SQuAD v2) — creada por init-debug.sh --squad"
else
  KB_NAME="Debug KB $TIMESTAMP"
  KB_DESC="KB de prueba creada por init-debug.sh"
fi
KB=$(curl -sf -X POST "$BASE/api/knowledge-bases" -H "$AUTH_HDR" -H 'Content-Type: application/json' -d "{
  \"name\": \"$KB_NAME\",
  \"description\": \"$KB_DESC\",
  \"chunking_config\": {\"strategy\": \"fixed\", \"chunk_size\": 600, \"chunk_overlap\": 100},
  \"embedding_selection\": {
    \"provider_id\": \"ollama\",
    \"credential_id\": \"$CRED_ID\",
    \"model_id\": \"$EMBED_MODEL\",
    \"dim\": $EMBED_DIM
  }
}")
KB_ID=$(echo "$KB" | jq -r .id)
ok "KB: $KB_ID ($KB_NAME)"

# --- 5. Upload documents ---
log "Uploading sample documents..."
if [[ -n "$SQUAD" ]]; then
  SEED_DIR="$REPO_ROOT/eval/seeds/squad"   # 38 SQuAD v2 context paragraphs (doc_only eval)
else
  SEED_DIR="$REPO_ROOT/eval/seed-docs"
fi
[[ -d "$SEED_DIR" ]] || err "Seed docs dir not found: $SEED_DIR"

# Use seed docs from the repo — single source of truth.
DOCS=$(mktemp -d)
trap "rm -rf $DOCS" EXIT
cp "$SEED_DIR"/*.txt "$DOCS/"

for f in $(cd "$DOCS" && ls *.txt); do
  RESP=$(curl -sf -X POST "$BASE/api/knowledge-bases/$KB_ID/sources/documents" \
    -H "$AUTH_HDR" -F "file=@$DOCS/$f;type=text/plain")
  JOB_ID=$(echo "$RESP" | jq -r .job_id)
  log "  Subido $f → job $JOB_ID"

  # Poll
  for i in $(seq 1 60); do
    STATE=$(curl -sf -H "$AUTH_HDR" "$BASE/api/ingestion-jobs/$JOB_ID" | jq -r .status)
    if [[ "$STATE" == "done" ]]; then ok "  $f ingestado"; break; fi
    if [[ "$STATE" == "failed" ]]; then
      ERR=$(curl -sf -H "$AUTH_HDR" "$BASE/api/ingestion-jobs/$JOB_ID" | jq -r '.error // "unknown"')
      err "  $f ingestion FAILED: $ERR"
    fi
    printf "."
    sleep 2
  done
done
echo

# --- 6. Seed MySQL with sample data (skipped for --squad: doc_only eval) ---
if [[ -n "$SQUAD" ]]; then
  log "SQuAD mode: skipping MySQL seed + attach (doc_only)."
else
log "Seeding MySQL with sample 'customers' table..."
docker exec -i "$MYSQL_CONTAINER" mysql -u root -prootpw "$MYSQL_DB" 2>/dev/null << 'EOSQL'
CREATE TABLE IF NOT EXISTS customers (
  id INT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(80) NOT NULL,
  email VARCHAR(120) NOT NULL UNIQUE,
  country VARCHAR(60),
  signup_date DATE,
  total_orders INT DEFAULT 0
);

INSERT IGNORE INTO customers (id, name, email, country, signup_date, total_orders) VALUES
  (1, 'Ada Lovelace', 'ada@example.com',   'UK',    '2024-01-10', 42),
  (2, 'Alan Turing', 'alan@example.com',   'UK',    '2024-02-14', 17),
  (3, 'Grace Hopper', 'grace@example.com', 'USA',   '2024-03-21',  8),
  (4, 'Donald Knuth', 'don@example.com',   'USA',   '2024-04-05', 33),
  (5, 'Edsger Dijkstra', 'edsger@example.com', 'NL', '2024-05-30', 5);

CREATE TABLE IF NOT EXISTS products (
  id INT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(80) NOT NULL,
  category VARCHAR(40),
  price_eur DECIMAL(8,2)
);

INSERT IGNORE INTO products (id, name, category, price_eur) VALUES
  (1, 'Mechanical Keyboard', 'Hardware', 129.99),
  (2, 'Standing Desk',       'Furniture', 349.00),
  (3, 'Noise-cancelling Headphones', 'Hardware', 249.50),
  (4, 'Whiteboard A1', 'Office', 79.00);
EOSQL
ok "MySQL seeded (customers + products)"

# --- 7. Attach MySQL as a SQL source ---
log "Attaching MySQL to the KB..."
ATTACH=$(curl -s -X POST "$BASE/api/knowledge-bases/$KB_ID/sources/databases" \
  -H "$AUTH_HDR" -H 'Content-Type: application/json' -d "{
    \"driver\": \"mysql\",
    \"host\": \"$MYSQL_HOST\",
    \"port\": $MYSQL_PORT,
    \"db_name\": \"$MYSQL_DB\",
    \"username\": \"$MYSQL_USER\",
    \"password\": \"$MYSQL_PASSWORD\"
  }")
if echo "$ATTACH" | jq -e .source_id >/dev/null 2>&1; then
  DB_SRC_ID=$(echo "$ATTACH" | jq -r .source_id)
  TABLES=$(echo "$ATTACH" | jq -r .snapshot_tables)
  ok "MySQL attached as source $DB_SRC_ID (snapshot: $TABLES tablas)"
else
  warn "MySQL attach failed: $ATTACH"
fi
fi  # end non-SQUAD MySQL block

# --- 8. Create chatbot ---
log "Creating Chatbot..."
if [[ -n "$SQUAD" ]]; then
  BOT_NAME="SQuAD Bot $TIMESTAMP"
  BOT_DESC="Bot doc_only para eval SQuAD v2"
  BOT_PROMPT="You are a question-answering assistant. Answer the user's question concisely in English, using ONLY the provided documents. If the documents do not contain the answer, say you don't know."
else
  BOT_NAME="Debug Bot $TIMESTAMP"
  BOT_DESC="Bot de prueba con KB de documentos y SQL"
  BOT_PROMPT="Eres un asistente de prueba. Responde en español, usa los documentos y la base de datos cuando sea relevante."
fi
BOT=$(curl -sf -X POST "$BASE/api/chatbots" -H "$AUTH_HDR" -H 'Content-Type: application/json' -d "{
  \"name\": \"$BOT_NAME\",
  \"description\": \"$BOT_DESC\",
  \"system_prompt\": \"$BOT_PROMPT\",
  \"llm_selection\": {\"provider_id\":\"ollama\",\"credential_id\":\"$CRED_ID\",\"model_id\":\"$LLM_MODEL\"},
  \"kb_ids\": [\"$KB_ID\"],
  \"pipeline_config\": {
    \"top_k\": 5,
    \"score_threshold\": 0.0,
    \"agentic_mode\": true,
    \"max_retrieval_iterations\": 3,
    \"enable_reranker\": false,
    \"reranker_initial_top_k\": 30,
    \"abstain_when_insufficient\": true,
    \"generation\": {\"temperature\": 0.3, \"max_tokens\": 1024}
  }
}")
BOT_ID=$(echo "$BOT" | jq -r .id)
PUBLIC_KEY=$(echo "$BOT" | jq -r .public_key)
ok "Chatbot: $BOT_ID (public_key: ${PUBLIC_KEY:0:16}…)"

# --- 9. Summary ---
cat <<EOF

${GREEN}========================================================================${RESET}
${GREEN}  Sistema inicializado.${RESET}

  Usuario:     $EMAIL  /  $PASSWORD
  Tenant:      $TENANT_ID
  KB:          $KB_ID  ($KB_NAME)
  MySQL src:   ${DB_SRC_ID:-${SQUAD:+(skipped — SQuAD doc_only)}}
  Chatbot:     $BOT_ID
  Public key:  $PUBLIC_KEY
  Embedding:   $EMBED_MODEL ($EMBED_DIM d)
  LLM:         $LLM_MODEL

  Abre el frontend en:
    http://localhost:3000/login            ← entra con $EMAIL / $PASSWORD
    http://localhost:3000/inspect          ← ver toda la info del tenant
    http://localhost:3000/knowledge/$KB_ID
    http://localhost:3000/chatbots/$BOT_ID/playground

  Para empezar de cero:
    cd infra && docker compose down -v && bash ../scripts/setup.sh
${GREEN}========================================================================${RESET}
EOF
