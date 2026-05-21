# TFM RAG Chatbot Platform

Herramienta para configurar y desplegar chatbots RAG conectados a fuentes de
conocimiento (documentos + bases de datos SQL). Pensada para usuarios no
expertos. Es el proyecto del **TFM de Ade Cabo**.

Este repo contiene **el backend** (FastAPI), la infra
(`docker-compose` con Postgres + Qdrant + Ollama) y los planes de
implementación. El frontend (Next.js) y el widget embebible aún no están
implementados.

---

## Estado actual

8 de 17 capabilities (CAPs) implementadas. La demo M2 está operativa
end-to-end: un usuario se registra, crea una `KnowledgeBase` con embedding
Ollama, sube un documento, y ve el `ingestion_job` progresar hasta que el
contenido queda indexado en Qdrant.

| Hito | Estado |
|---|---|
| M1 — Onboarding (auth + credenciales) | ✅ Completo |
| M2 — KnowledgeBases con documentos | ✅ Demo MVP (upload + PDF/TXT + Ollama + chunker fijo) |
| M3 — Chatbot básico con RAG documental | ⏳ Pendiente |
| M4 — Bases de datos SQL como fuente | ⏳ Pendiente |
| M5–M7 | ⏳ Pendiente |

Para el detalle granular (qué plans hay, qué bugs hay, qué decidir en la
próxima sesión), ver **[`handover.md`](handover.md)**. Para la spec
ejecutable completa, ver
[`docs/superpowers/specs/2026-05-19-tfm-roadmap-funcional-design.html`](docs/superpowers/specs/2026-05-19-tfm-roadmap-funcional-design.html).

---

## Requisitos previos

- **Python 3.12** (no vale 3.11 ni 3.13 — el `pyproject.toml` lo exige).
- **Docker** + **plugin `docker compose`** (no el viejo `docker-compose` con
  guión). En WSL2: habilitar "WSL Integration" en Docker Desktop → Settings →
  Resources.
- ~6 GB de disco libre para imágenes Docker (postgres ~80MB, qdrant ~50MB,
  **ollama ~3.9 GB**) + ~6 GB más para los modelos que Ollama pre-pulla
  (`bge-m3` ~1.2 GB, `llama3.1` ~4.7 GB).
- Linux / macOS / WSL2. Windows nativo no está soportado.

---

## Instalación rápida (fresh PC)

```bash
git clone <repo-url> tfm-rag-chatbot-deploy-tool
cd tfm-rag-chatbot-deploy-tool
bash scripts/setup.sh
```

`scripts/setup.sh` es idempotente. Hace todo esto:

1. Verifica prerequisitos (Python 3.12, Docker, compose plugin).
2. Crea `backend/.venv` e instala las deps en modo editable (`pip install -e
   ./backend[dev]`).
3. Genera `infra/.env` desde `infra/.env.example` con secretos aleatorios
   (`JWT_SECRET` con `secrets.token_urlsafe(32)`, `FERNET_KEY` con
   `cryptography.fernet.Fernet.generate_key()`) y un `STORAGE_LOCAL_PATH`
   utilizable en dev (`/tmp/tfm_rag_storage`).
4. `docker compose up -d postgres qdrant ollama` y espera a que reporten
   `healthy` (hasta 3 minutos en el primer arranque; Ollama tarda porque
   pre-pulla `bge-m3` + `llama3.1`).
5. `alembic upgrade head` contra el Postgres recién levantado.
6. Corre la suite de tests unitarios como smoke check.

Puedes re-ejecutarlo cuando quieras: si la venv ya existe, no la recrea; si
los secretos ya son aleatorios, no los toca; si las migraciones ya están
aplicadas, son no-op.

---

## Arrancar el backend

Después de `setup.sh`, hay dos formas equivalentes:

### Con el helper

```bash
bash scripts/run-backend.sh           # uvicorn en :8000 con --reload
bash scripts/run-backend.sh --port 9000 --no-reload
```

### A mano

```bash
cd backend
source .venv/bin/activate

# Variables que la API + alembic + tests esperan.
# Usa LOCALHOST (no el hostname `postgres`) para uvicorn fuera del container.
export POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag'
export QDRANT_URL='http://localhost:6333'
export OLLAMA_BASE_URL='http://localhost:11434'
export JWT_SECRET=$(grep '^JWT_SECRET=' ../infra/.env | cut -d= -f2-)
export FERNET_KEY=$(grep '^FERNET_KEY=' ../infra/.env | cut -d= -f2-)
export STORAGE_LOCAL_PATH=/tmp/tfm_rag_storage

uvicorn tfm_rag.infrastructure.api.app:app --reload --port 8000
```

La API queda en `http://localhost:8000`. Lo más útil:

- **Swagger UI**: `http://localhost:8000/docs` — explora y ejecuta todos los
  endpoints, con "Authorize" para meter el Bearer token.
- **OpenAPI JSON**: `http://localhost:8000/openapi.json`.
- **Health**: `http://localhost:8000/health`.

---

## Demo M2 desde la terminal

Esto reproduce el flujo end-to-end que pasa en el integration test
`test_doc_ingestion_flow.py`:

```bash
# 1. Health
curl -s http://localhost:8000/health | jq

# 2. Registrarse → token + tenant_id + ollama default credential
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","password":"correctpassword"}' | jq -r .token)

# 3. Encontrar el credential default de Ollama
CRED_ID=$(curl -s http://localhost:8000/api/credentials \
  -H "Authorization: Bearer $TOKEN" | jq -r '.[] | select(.provider_id=="ollama") | .id')

# 4. Crear una KnowledgeBase con embedding Ollama bge-m3 (1024 dims)
KB_ID=$(curl -s -X POST http://localhost:8000/api/knowledge-bases \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{
        \"name\": \"Manuales\",
        \"embedding_selection\": {
          \"provider_id\": \"ollama\",
          \"credential_id\": \"$CRED_ID\",
          \"model_id\": \"bge-m3\",
          \"dim\": 1024
        }
      }" | jq -r .id)

# 5. Subir un .txt y disparar la ingestión
echo "Lorem ipsum dolor sit amet. Consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris." > /tmp/sample.txt

JOB_ID=$(curl -s -X POST "http://localhost:8000/api/knowledge-bases/$KB_ID/sources/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/sample.txt;type=text/plain" | jq -r .job_id)

# 6. Polling — verás status pasar de queued → running → done con progress 0→100
watch -n 1 "curl -s http://localhost:8000/api/ingestion-jobs/$JOB_ID -H 'Authorization: Bearer $TOKEN' | jq"

# 7. Detalle de la KB con las sources persistidas
curl -s "http://localhost:8000/api/knowledge-bases/$KB_ID" \
  -H "Authorization: Bearer $TOKEN" | jq
```

Pruébalo también con un PDF (`-F "file=@/path/to/file.pdf;type=application/pdf"`).

---

## Estructura del repositorio

```
.
├── backend/                       FastAPI app (toda la lógica)
│   ├── src/tfm_rag/
│   │   ├── domain/                Entidades, value objects, errores, ports
│   │   ├── application/           Use cases (auth, integrations, knowledge)
│   │   └── infrastructure/        Adapters: persistence, api, jobs,
│   │                              storage, document_loaders, chunkers,
│   │                              embedders, vector_store, secrets
│   ├── alembic/                   Migraciones (0001-0005 hasta plan #8)
│   ├── tests/
│   │   ├── unit/                  No requieren Docker. ~61 tests.
│   │   └── integration/           Requieren stack viva. ~12 tests.
│   ├── pyproject.toml             Deps + dev deps
│   └── README.md                  Detalles del backend
│
├── infra/
│   ├── docker-compose.yml         Postgres + Qdrant + Ollama (+ backend)
│   ├── .env.example               Plantilla — copiada a .env por setup.sh
│   └── seed/ollama_pull.sh        Pre-pulla bge-m3 y llama3.1 al arrancar Ollama
│
├── docs/
│   ├── superpowers/
│   │   ├── specs/2026-05-19-…html  Spec ejecutable HTML (1500+ líneas)
│   │   └── plans/*.md              Plans de implementación (uno por CAP)
│   └── TFM - Segunda entrega…pdf   Memoria académica original del TFM
│
├── scripts/
│   ├── setup.sh                   Bootstrap idempotente para PC nuevo
│   └── run-backend.sh             Lanzar uvicorn con las env vars correctas
│
├── handover.md                    Estado del proyecto + qué viene después
├── subagent-questions.md          Log de preguntas pendientes de subagents
└── README.md                      Este fichero
```

---

## Tests

```bash
cd backend
source .venv/bin/activate

# Variables que los tests esperan (los unit los ignoran; los integration sí):
export POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag'
export QDRANT_URL='http://localhost:6333'
export OLLAMA_BASE_URL='http://localhost:11434'
export JWT_SECRET=$(grep '^JWT_SECRET=' ../infra/.env | cut -d= -f2-)
export FERNET_KEY=$(grep '^FERNET_KEY=' ../infra/.env | cut -d= -f2-)
export STORAGE_LOCAL_PATH=/tmp/tfm_rag_storage

# Unitarios — rápidos, no requieren Docker
pytest tests/ -m "not integration"

# Integration — requieren Docker arriba + migraciones aplicadas
pytest tests/integration -m integration -v

# Lint + tipos
ruff check .
mypy src/
```

---

## Operaciones comunes

### Resetear el estado de la BD (perder todos los datos)

```bash
docker exec tfm-rag-postgres-1 psql -U tfm -d tfm_rag -c \
  "DROP TABLE IF EXISTS ingestion_jobs, sources, knowledge_bases, provider_credentials, users, tenants, alembic_version CASCADE;"
cd backend && alembic upgrade head
```

### Tirar todo el stack y empezar de cero

```bash
cd infra
docker compose down -v          # -v borra también los volúmenes (datos persistentes)
bash ../scripts/setup.sh        # vuelve a montar todo
```

### Ver logs de los servicios

```bash
cd infra
docker compose logs -f ollama   # o postgres / qdrant
```

### Ver qué hay dentro de Postgres

```bash
docker exec -it tfm-rag-postgres-1 psql -U tfm -d tfm_rag
# Dentro:
\dt                              # listar tablas
SELECT id, email, tenant_id FROM users;
SELECT id, name, embedding_selection FROM knowledge_bases;
SELECT id, status, progress FROM ingestion_jobs ORDER BY started_at DESC;
```

### Ver qué hay dentro de Qdrant

```bash
curl -s http://localhost:6333/collections | jq
# Reemplaza tenant_id por el real:
curl -s "http://localhost:6333/collections/kb_chunks__<tenant_id>__1024/points/scroll" \
  -H 'Content-Type: application/json' -d '{"limit": 5, "with_payload": true}' | jq
```

---

## Frontend

No existe todavía. El roadmap del spec describe un panel Next.js con rutas
`/login`, `/register`, `/`, `/knowledge`, `/knowledge/new`, `/knowledge/:id`,
`/chatbots`, `/settings/integraciones`, pero no hay plan escrito ni código.
La forma actual de "ver" el sistema funcionando es vía **Swagger UI** en
`http://localhost:8000/docs` o vía los `curl` de la sección "Demo M2".

---

## Troubleshooting

### `setup.sh` falla con "WSL2 detected but docker info failed"
Abre Docker Desktop → Settings → Resources → WSL Integration, marca tu
distribución de WSL2 y aplica. Luego cierra y vuelve a abrir la terminal.

### Ollama dual / embeddings dan timeout o "no embedding"
Es posible tener un Ollama *nativo* del host **y** el container
`tfm-rag-ollama-1` peleándose por el puerto 11434. Verifica cuál responde:

```bash
curl -s http://localhost:11434/api/tags | jq '.models[].name'
```

Si no aparece `bge-m3`, la instancia que ganó no es la del container. Opciones:

- Parar el Ollama del host: `systemctl --user stop ollama` (Linux) o cerrar la
  app Ollama (macOS).
- O pullar el modelo en la instancia activa: `docker exec tfm-rag-ollama-1
  ollama pull bge-m3` (si el container es la activa) o `ollama pull bge-m3`
  (si lo es el host).

### `STORAGE_LOCAL_PATH=/data/storage` permission denied
El default del `.env.example` apunta a `/data/storage`, que requiere root.
`setup.sh` ya lo sobrescribe a `/tmp/tfm_rag_storage` automáticamente. Si
estás corriendo a mano y ves esto, exporta manualmente:

```bash
export STORAGE_LOCAL_PATH=/tmp/tfm_rag_storage
mkdir -p $STORAGE_LOCAL_PATH
```

### Tests de integración fallan con `RuntimeError: ... different loop`
Bug conocido del `_session_factory` global cuando pytest-asyncio crea un loop
por test. La fixture de cleanup en los tests ya lo resetea
(`_deps._session_factory = None`); si añades un test nuevo de integración que
toca routers, copia esa fixture.

### `pip install` muy lento o falla en la red
Algunas deps son pesadas (`qdrant-client`, `pypdf`, `httpx`). En WSL2 a veces
ayuda configurar `pip config set global.index-url https://pypi.org/simple` y
asegurarse de que la fecha del sistema está sincronizada.

---

## Licencia

MIT. Ver [`LICENSE`](LICENSE).
