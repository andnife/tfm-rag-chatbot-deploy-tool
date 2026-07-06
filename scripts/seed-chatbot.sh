#!/usr/bin/env bash
# seed-chatbot.sh — Create a full chatbot instance via the API.
#
# Steps:
#   1. Register (or login) a test user
#   2. Fetch the default Ollama credential
#   3. Auto-detect available Ollama models
#   4. Create a Knowledge Base with Ollama embeddings
#   5. Upload sample documents
#   6. Wait for ingestion to complete
#   7. Verify search works
#   8. Create a Chatbot linked to the KB
#   9. Send a test chat message
#
# Usage:
#   bash scripts/seed-chatbot.sh
#   bash scripts/seed-chatbot.sh --email foo@bar.com --password secret123
#
# Requires: curl, jq, backend running on :8000, Ollama running on :11434

set -euo pipefail

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BLUE=$'\033[34m'; RESET=$'\033[0m'
log()  { printf "%s[seed]%s %s\n" "$BLUE"  "$RESET" "$*"; }
ok()   { printf "%s[ ok ]%s %s\n" "$GREEN" "$RESET" "$*"; }
warn() { printf "%s[warn]%s %s\n" "$YELLOW" "$RESET" "$*"; }
err()  { printf "%s[err ]%s %s\n" "$RED"   "$RESET" "$*" >&2; exit 1; }

# --- Parse args ---
EMAIL="seed-test@example.com"
PASSWORD="Test1234!"
for arg in "$@"; do
  case "$arg" in
    --email)    EMAIL="$2"; shift 2 ;;
    --email=*)  EMAIL="${arg#*=}"; shift ;;
    --password) PASSWORD="$2"; shift 2 ;;
    --password=*) PASSWORD="${arg#*=}"; shift ;;
  esac
done

BASE="http://localhost:8000"

# --- Preflight ---
command -v curl >/dev/null || err "curl not found"
command -v jq   >/dev/null || err "jq not found"
curl -sf "$BASE/health" >/dev/null 2>&1 || err "Backend not reachable at $BASE — is it running?"

# --- Auto-detect available Ollama models ---
log "Detecting Ollama models..."
AVAILABLE_MODELS=$(curl -sf http://localhost:11434/api/tags 2>/dev/null | jq -r '.models[].name' 2>/dev/null || echo "")

# Pick embedding model (prefer nomic-embed-text, fallback to bge-m3)
EMBED_MODEL=""
EMBED_DIM=0
if echo "$AVAILABLE_MODELS" | grep -q "nomic-embed-text"; then
  EMBED_MODEL="nomic-embed-text"
  EMBED_DIM=768
elif echo "$AVAILABLE_MODELS" | grep -q "bge-m3"; then
  EMBED_MODEL="bge-m3"
  EMBED_DIM=1024
fi
[[ -n "$EMBED_MODEL" ]] || err "No embedding model found in Ollama. Pull one: ollama pull nomic-embed-text"
ok "Embedding model: $EMBED_MODEL (dim=$EMBED_DIM)"

# Pick LLM model (prefer hermes3, then llama3.1, mistral, gemma2)
LLM_MODEL=""
for candidate in hermes3 llama3.1 mistral gemma2; do
  if echo "$AVAILABLE_MODELS" | grep -q "$candidate"; then
    LLM_MODEL="$candidate"
    break
  fi
done
[[ -n "$LLM_MODEL" ]] || err "No LLM model found in Ollama. Pull one: ollama pull hermes3"
ok "LLM model: $LLM_MODEL"

# ============================================================
# Step 1: Register user
# ============================================================
log "Step 1: Registering user $EMAIL..."
REGISTER_RESP=$(curl -s -w "\n%{http_code}" -X POST "$BASE/api/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
HTTP_CODE=$(echo "$REGISTER_RESP" | tail -1)
BODY=$(echo "$REGISTER_RESP" | sed '$d')

if [[ "$HTTP_CODE" == "201" ]] && echo "$BODY" | jq -e '.access_token' >/dev/null 2>&1; then
  ok "User registered"
  REGISTER_RESP="$BODY"
else
  log "Register failed (HTTP $HTTP_CODE), trying login..."
  REGISTER_RESP=$(curl -sf -X POST "$BASE/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}") || err "Login failed"
  ok "Logged in"
fi

TOKEN=$(echo "$REGISTER_RESP" | jq -r '.access_token')
TENANT_ID=$(echo "$REGISTER_RESP" | jq -r '.tenant_id')
AUTH="Authorization: Bearer $TOKEN"
ok "Token acquired (tenant: $TENANT_ID)"

# ============================================================
# Step 2: Get default Ollama credential
# ============================================================
log "Step 2: Fetching Ollama credential..."
CREDENTIALS=$(curl -sf -H "$AUTH" "$BASE/api/credentials")
OLLAMA_CRED_ID=$(echo "$CREDENTIALS" | jq -r '.[] | select(.provider_id=="ollama") | .id' | head -1)
[[ -n "$OLLAMA_CRED_ID" && "$OLLAMA_CRED_ID" != "null" ]] || err "No Ollama credential found"
ok "Ollama credential: $OLLAMA_CRED_ID"

# ============================================================
# Step 3: Create Knowledge Base
# ============================================================
log "Step 3: Creating Knowledge Base..."
KB_RESP=$(curl -sf -X POST "$BASE/api/knowledge-bases" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"Documentación RAG\",
    \"description\": \"Documentos de prueba para el chatbot RAG\",
    \"chunking_config\": {
      \"strategy\": \"recursive\",
      \"chunk_size\": 800,
      \"chunk_overlap\": 150
    },
    \"embedding_selection\": {
      \"credential_id\": \"$OLLAMA_CRED_ID\",
      \"model_id\": \"$EMBED_MODEL\",
      \"dim\": $EMBED_DIM
    }
  }")

KB_ID=$(echo "$KB_RESP" | jq -r '.id')
ok "Knowledge Base created: $KB_ID"

# ============================================================
# Step 4: Create sample documents and upload
# ============================================================
log "Step 4: Uploading sample documents..."

DOCS_DIR=$(mktemp -d)
trap "rm -rf $DOCS_DIR" EXIT

cat > "$DOCS_DIR/resumen.txt" << 'DOCEOF'
Title: Plataforma RAG para Chatbots

Resumen del proyecto:
Esta plataforma permite crear chatbots inteligentes basados en Retrieval-Augmented Generation (RAG).
Los usuarios pueden subir documentos PDF o conectar bases de datos SQL, que son procesados,
divididos en chunks y vectorizados para su posterior recuperación.

Características principales:
1. Multi-tenant: cada usuario tiene su propio espacio aislado.
2. Knowledge Bases: los documentos se organizan en bases de conocimiento.
3. Ingestión flexible: soporte para PDF, TXT y bases de datos SQL (PostgreSQL, MySQL).
4. Chatbots configurables: cada chatbot tiene su propio LLM, pipeline de recuperación y widget embebido.
5. Widget embebido: los chatbots se pueden integrar en cualquier web mediante un snippet de JavaScript.

Arquitectura técnica:
- Backend: FastAPI + SQLAlchemy 2 async + Alembic + PostgreSQL
- Vector store: Qdrant
- LLM local: Ollama
- Frontend: React + Next.js + TypeScript + Tailwind + shadcn/ui
- Deploy: Docker Compose

El sistema utiliza un pipeline agentic donde el LLM decide cuándo buscar en la documentación
y cuándo responder directamente. Esto permite manejar preguntas que requieren información
específica del corpus documental así como preguntas generales.
DOCEOF

cat > "$DOCS_DIR/api_guide.txt" << 'DOCEOF'
Title: Guía de la API REST

Endpoints principales:

Autenticación:
- POST /api/auth/register — Crear cuenta nueva (email + password, mínimo 8 caracteres)
- POST /api/auth/login — Iniciar sesión, devuelve JWT token
- GET /api/auth/me — Información del usuario autenticado

Knowledge Bases:
- POST /api/knowledge-bases — Crear nueva KB con configuración de chunking y embeddings
- GET /api/knowledge-bases — Listar todas las KBs del tenant
- POST /api/knowledge-bases/{id}/sources/documents — Subir documento (multipart)
- POST /api/knowledge-bases/{id}/sources/databases — Conectar base de datos SQL
- POST /api/knowledge-bases/{id}/search — Búsqueda semántica sobre los chunks

Chatbots:
- POST /api/chatbots — Crear chatbot con configuración de LLM, KBs y pipeline
- GET /api/chatbots — Listar chatbots
- POST /api/chatbots/{id}/chat — Enviar mensaje al chatbot
- GET /api/chatbots/{id}/sessions — Listar sesiones de chat

Widget embebido:
- GET /api/public/chatbots/{public_key}/config — Configuración pública del widget
- POST /api/public/chatbots/{public_key}/chat — Chat público (sin autenticación JWT)

El chatbot utiliza un pipeline con las siguientes herramientas:
- search_docs: busca chunks relevantes en las knowledge bases asignadas
- final_answer: genera la respuesta final basada en los documentos encontrados
- abstain: se niega a responder si no hay información suficiente
DOCEOF

UPLOAD1=$(curl -sf -X POST "$BASE/api/knowledge-bases/$KB_ID/sources/documents" \
  -H "$AUTH" -F "file=@$DOCS_DIR/resumen.txt")
JOB1=$(echo "$UPLOAD1" | jq -r '.job_id')
ok "Document 1 uploaded (job: $JOB1)"

UPLOAD2=$(curl -sf -X POST "$BASE/api/knowledge-bases/$KB_ID/sources/documents" \
  -H "$AUTH" -F "file=@$DOCS_DIR/api_guide.txt")
JOB2=$(echo "$UPLOAD2" | jq -r '.job_id')
ok "Document 2 uploaded (job: $JOB2)"

# ============================================================
# Step 5: Wait for ingestion
# ============================================================
log "Step 5: Waiting for ingestion to complete..."

wait_job() {
  local job_id="$1" label="$2"
  local attempts=0
  while (( attempts < 90 )); do
    local resp
    resp=$(curl -sf -H "$AUTH" "$BASE/api/ingestion-jobs/$job_id" 2>/dev/null || echo '{"status":"pending"}')
    local status
    status=$(echo "$resp" | jq -r '.status')
    case "$status" in
      done)
        echo
        ok "$label done"
        return 0
        ;;
      failed)
        echo
        local errmsg
        errmsg=$(echo "$resp" | jq -r '.error // "unknown"')
        err "$label FAILED: $errmsg"
        return 1
        ;;
      *)
        printf "."
        sleep 2
        (( attempts++ ))
        ;;
    esac
  done
  echo
  err "$label timed out after 180s"
}

wait_job "$JOB1" "Doc 1 ingestion"
wait_job "$JOB2" "Doc 2 ingestion"

# ============================================================
# Step 6: Verify search works
# ============================================================
log "Step 6: Testing semantic search..."
SEARCH_RESP=$(curl -sf -X POST "$BASE/api/knowledge-bases/$KB_ID/search" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"query": "Que es RAG?", "top_k": 3}')
HIT_COUNT=$(echo "$SEARCH_RESP" | jq 'length')
ok "Search returned $HIT_COUNT results"
echo "$SEARCH_RESP" | jq -r '.[] | "  [\(.score | . * 100 | round / 100)%] \(.content[0:80])..."' 2>/dev/null || true

# ============================================================
# Step 7: Create Chatbot
# ============================================================
log "Step 7: Creating Chatbot..."
CHATBOT_RESP=$(curl -sf -X POST "$BASE/api/chatbots" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d "{
    \"name\": \"Asistente RAG\",
    \"description\": \"Chatbot de prueba de la plataforma RAG\",
    \"system_prompt\": \"Eres un asistente experto en la plataforma RAG. Responde en español usando la información de los documentos proporcionados. Si no tienes información suficiente, indica que no puedes responder.\",
    \"llm_selection\": {
      \"credential_id\": \"$OLLAMA_CRED_ID\",
      \"model_id\": \"$LLM_MODEL\"
    },
    \"kb_ids\": [\"$KB_ID\"],
    \"pipeline_config\": {
      \"top_k\": 5,
      \"score_threshold\": 0.3,
      \"agentic_mode\": true,
      \"max_retrieval_iterations\": 3,
      \"abstain_when_insufficient\": true,
      \"generation\": {\"temperature\": 0.3, \"max_tokens\": 1024}
    },
    \"widget_config\": {
      \"theme\": \"light\",
      \"title\": \"Asistente RAG\",
      \"welcome_message\": \"¡Hola! Soy el asistente RAG. Pregúntame sobre la plataforma.\",
      \"placeholder\": \"Escribe tu pregunta...\"
    }
  }")

CHATBOT_ID=$(echo "$CHATBOT_RESP" | jq -r '.id')
PUBLIC_KEY=$(echo "$CHATBOT_RESP" | jq -r '.public_key')
ok "Chatbot created: $CHATBOT_ID"
ok "Public key: $PUBLIC_KEY"

# ============================================================
# Step 8: Test chat
# ============================================================
log "Step 8: Sending test chat message..."
CHAT_RESP=$(curl -sf -X POST "$BASE/api/chatbots/$CHATBOT_ID/chat" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"message": "Que es esta plataforma? Como funciona el pipeline RAG?"}')

echo ""
echo "=========================================="
echo "  Chatbot Response"
echo "=========================================="
echo "$CHAT_RESP" | jq -r '.content'
echo ""
echo "Citations:"
echo "$CHAT_RESP" | jq -r '.citations[]? | "  - \(.source_name): \(.location)"' 2>/dev/null || echo "  (none)"
echo ""
echo "Iterations:"
echo "$CHAT_RESP" | jq -r '.iterations[]? | "  [\(.tool)] \(.query // "n/a") (\(.latency_ms)ms)"' 2>/dev/null || echo "  (none)"
echo "=========================================="

# ============================================================
# Summary
# ============================================================
echo ""
echo "=========================================="
echo "  Seed Complete!"
echo "=========================================="
echo "  User:        $EMAIL"
echo "  Tenant:      $TENANT_ID"
echo "  KB:          $KB_ID"
echo "  Chatbot:     $CHATBOT_ID"
echo "  Public key:  $PUBLIC_KEY"
echo "  LLM:         $LLM_MODEL"
echo "  Embeddings:  $EMBED_MODEL ($EMBED_DIM d)"
echo ""
echo "  Frontend:    http://localhost:3000"
echo "  Backend:     http://localhost:8000/docs"
echo ""
echo "  Widget embed:"
echo "    <script src=\"http://localhost:8000/widget/widget.js\""
echo "            data-public-key=\"$PUBLIC_KEY\"></script>"
echo "=========================================="
