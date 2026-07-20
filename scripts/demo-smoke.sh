#!/usr/bin/env bash
# demo-smoke.sh — Smoke-test the demo chatbot end-to-end (same endpoint the
# Playground uses). Logs in as the demo user, sends a set of questions, and
# prints latency + answer + citation count + routing info for each.
#
# Usage: bash scripts/demo-smoke.sh [--email demo@fake.com] [--password Demo1234]
set -euo pipefail
EMAIL="demo@fake.com"; PASSWORD="Demo1234"; BOT_NAME="Asistente Universidad Europea"
while (($#)); do case "$1" in
  --email) EMAIL="$2"; shift 2;; --password) PASSWORD="$2"; shift 2;;
  --bot) BOT_NAME="$2"; shift 2;; *) shift;; esac; done
BASE=http://localhost:8000

AUTH=$(curl -s -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
TOKEN=$(echo "$AUTH" | jq -r .access_token)
[[ -n "$TOKEN" && "$TOKEN" != "null" ]] || { echo "login failed: $AUTH"; exit 1; }
H="Authorization: Bearer $TOKEN"
BOT_ID=$(curl -s -H "$H" "$BASE/api/chatbots" | jq -r --arg n "$BOT_NAME" '[.[]|select(.name==$n)][0].id')
echo "bot: $BOT_ID"

ask() {
  local q="$1"
  echo; echo "════════════════════════════════════════════════════════════════"
  echo "Q: $q"
  local t0 t1 resp
  t0=$(date +%s.%N)
  resp=$(curl -s -X POST "$BASE/api/chatbots/$BOT_ID/chat" -H "$H" -H 'Content-Type: application/json' \
    -d "$(jq -n --arg m "$q" '{message:$m}')")
  t1=$(date +%s.%N)
  printf "⏱  %.1fs   citas=%s  [%s]\n" \
    "$(echo "$t1 - $t0" | bc)" \
    "$(echo "$resp" | jq -r '(.citations|length) // 0')" \
    "$(echo "$resp" | jq -r '[.citations[]?.source_filename] | unique | join(", ")' 2>/dev/null)"
  echo "A: $(echo "$resp" | jq -r '.content' | head -c 600)"
}

for q in "$@"; do :; done  # no-op to allow sourcing
# --- Question bank ---
ask "¿En qué ciudades tiene campus la Universidad Europea?"
ask "¿Qué es el Creative Campus y qué se estudia allí?"
ask "¿Qué grados ofrece la Universidad Europea en el área de salud?"
ask "¿Ofrecen algún grado en Inteligencia Artificial? ¿En qué campus?"
ask "¿Puedo estudiar Diseño de Videojuegos de forma presencial? ¿Dónde?"
ask "¿Qué becas ofrece la universidad por buen expediente académico?"
ask "¿Hay becas para deportistas?"
ask "¿Cuáles son los pasos del proceso de admisión?"
ask "¿Los estudios incluyen prácticas en empresas?"
ask "¿Ofrece la universidad programas internacionales o de intercambio?"
# --- Abstention / honesty controls ---
ask "¿Cuánto cuesta exactamente la matrícula de un grado?"
ask "¿Quién es el rector actual de la universidad?"
ask "¿Cuál es el menú de la cafetería del campus de Alcobendas?"
echo
