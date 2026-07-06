#!/usr/bin/env bash
# Verify the whole MVP system: loud preflight (never silent) + smoke.
#
# Unlike `scripts/e2e.sh` (which uses `set -e` and can exit quietly if a
# prerequisite like Docker or Ollama is missing), this script checks every
# dependency explicitly, prints a clear ✓/✗ report with the exact fix, and only
# then runs the fast Playwright smoke that covers the MVP areas.
#
# Usage:
#   bash scripts/verify.sh              # preflight + fast smoke
#   bash scripts/verify.sh --preflight  # only the readiness checks (no smoke)
#
# Requires: Docker, Ollama (llama3.1 + bge-m3), Python venv in backend/, node.
set -uo pipefail   # NOTE: no `-e` — we want to report ALL problems, not bail.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

OLLAMA_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"
REQUIRED_MODELS=("llama3.1" "bge-m3")

# Local services must bypass any inherited corporate proxy so our own probes
# (and the backend the smoke launches) can reach localhost.
HAD_PROXY="${HTTP_PROXY:-${http_proxy:-}}"
export NO_PROXY="localhost,127.0.0.1,::1,postgres,qdrant,mysql_source,backend${NO_PROXY:+,$NO_PROXY}"
export no_proxy="$NO_PROXY"

GREEN="\033[32m"; RED="\033[31m"; YELLOW="\033[33m"; BOLD="\033[1m"; RESET="\033[0m"
FAILS=0
ok()   { printf "  ${GREEN}✓${RESET} %s\n" "$1"; }
bad()  { printf "  ${RED}✗${RESET} %s\n" "$1"; printf "      ${YELLOW}→ %s${RESET}\n" "$2"; FAILS=$((FAILS+1)); }
hdr()  { printf "\n${BOLD}%s${RESET}\n" "$1"; }

hdr "RAG Platform — verificación del sistema"

# ── 1. Repo prerequisites ────────────────────────────────────────────────────
hdr "1. Configuración y herramientas"
[ -f infra/.env ] && ok "infra/.env presente" \
  || bad "falta infra/.env" "cópialo desde infra/.env.example y rellena secretos"
[ -x backend/.venv/bin/python ] && ok "venv del backend presente" \
  || bad "falta backend/.venv" "crea el venv (ver scripts/setup.sh)"
command -v node >/dev/null && ok "node $(node -v)" \
  || bad "node no encontrado" "instala Node 20+"
if [ -n "$HAD_PROXY" ]; then
  ok "HTTP_PROXY detectado ($HAD_PROXY) — local va por NO_PROXY (Qdrant/Ollama bypass)"
else
  ok "sin HTTP_PROXY heredado"
fi

# ── 2. Docker daemon + compose services ──────────────────────────────────────
hdr "2. Docker"
if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  ok "demonio Docker activo"
else
  bad "Docker no disponible" "arranca Docker Desktop / el demonio (en WSL, ábrelo en Windows)"
fi

# ── 3. Ollama + modelos requeridos ───────────────────────────────────────────
hdr "3. Ollama (modelos locales)"
TAGS="$(curl -sf --max-time 4 "$OLLAMA_URL/api/tags" 2>/dev/null)"
if [ -n "$TAGS" ]; then
  ok "Ollama responde en $OLLAMA_URL"
  for m in "${REQUIRED_MODELS[@]}"; do
    if printf '%s' "$TAGS" | grep -q "\"$m"; then ok "modelo '$m' disponible"
    else bad "modelo '$m' no está" "ejecútalo: ollama pull $m"; fi
  done
else
  bad "Ollama no responde en $OLLAMA_URL" "arranca Ollama (ollama serve) y revisa OLLAMA_BASE_URL"
fi

# ── 4. Servicios HTTP (informativo — e2e.sh los levanta si faltan) ───────────
hdr "4. Servicios HTTP (se levantan solos si faltan)"
probe() { curl -sf -o /dev/null --max-time 3 "$1" && ok "$2"; return 0; }
probe http://localhost:8000/docs       "backend :8000"          || printf "  ${YELLOW}·${RESET} backend :8000 no responde (lo arranca el smoke)\n"
probe http://localhost:3001/login      "next :3001"             || printf "  ${YELLOW}·${RESET} next :3001 no responde (lo arranca el smoke)\n"

# ── Gate: prerequisites that the smoke cannot self-heal ──────────────────────
if [ "$FAILS" -gt 0 ]; then
  printf "\n${RED}${BOLD}Preflight con %d problema(s).${RESET} Resuélvelos antes del smoke.\n" "$FAILS"
  exit 1
fi
printf "\n${GREEN}${BOLD}Preflight OK.${RESET}\n"

if [ "${1:-}" = "--preflight" ]; then exit 0; fi

# ── 5. Smoke (fast Playwright project — cubre las áreas del MVP) ─────────────
hdr "5. Smoke e2e (proyecto fast)"
echo "[verify] delegando en scripts/e2e.sh --project=fast …"
bash scripts/e2e.sh --project=fast
rc=$?

hdr "Resultado"
if [ "$rc" -eq 0 ]; then
  printf "${GREEN}${BOLD}SISTEMA VERIFICADO ✓${RESET} (preflight + smoke fast en verde)\n"
else
  printf "${RED}${BOLD}SMOKE FALLÓ (exit %d)${RESET} — revisa la salida de Playwright arriba.\n" "$rc"
fi
exit "$rc"
