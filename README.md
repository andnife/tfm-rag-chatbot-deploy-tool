# RAG Chatbot Platform

Plataforma multi-tenant para configurar y desplegar **chatbots RAG** conectados
a fuentes de conocimiento heterogéneas: bases de conocimiento documentales
(PDF/TXT/DOCX) y **fuentes de datos SQL**. Cada chatbot resuelve preguntas
enrutando entre documentos, SQL o ambos, con un widget JS embebible en
cualquier web y un panel de evaluación (RAGAS) para medir calidad de
respuesta antes de pasar a producción.

Este repositorio contiene:
- **Backend** — FastAPI + Postgres + Qdrant + Ollama (async, arquitectura hexagonal)
- **Frontend** — Next.js App Router + Tailwind + shadcn/ui
- **Widget** — JS/CSS embebible, sirve desde el propio backend
- **Infra** — `docker-compose` (dev y prod) para Postgres + Qdrant + Ollama + MySQL (fuente SQL de demo)
- **Eval** — datasets de evaluación curados + runner RAGAS

> Este repositorio es el artefacto de software de mi Trabajo de Fin de Máster (TFM).

---

## Stack

| Capa | Tecnología |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.x async, Alembic, Pydantic v2 |
| Persistencia | PostgreSQL (datos de la app), Qdrant (vectores), MySQL (fuentes SQL de tenant/demo) |
| Inferencia | Ollama (local, gratis) u OpenAI/OpenAI-compatible por credencial de tenant |
| Evaluación | RAGAS (faithfulness, answer_relevancy, context_precision/recall) + métricas propias (routing_accuracy, abstain_accuracy) |
| Frontend | Next.js (App Router), TanStack Query, Tailwind, shadcn/ui, i18next |
| Widget | JS vanilla embebible vía `<script>`, sin build step |
| Infra | Docker Compose (dev + prod), nginx (prod), Alembic auto-migraciones |

---

## Arquitectura

El backend sigue **arquitectura hexagonal** (puertos y adaptadores):

- **`domain/`** — entidades, value objects, errores y **puertos** (`Protocol`s: repositorios, storage, embedders, etc.). Sin imports de FastAPI/SQLAlchemy/Qdrant — es Python puro.
- **`application/`** — casos de uso que orquestan el dominio recibiendo los puertos por inyección de dependencias (auth, integraciones, conocimiento, chat, evaluación).
- **`infrastructure/`** — adaptadores concretos que implementan los puertos: routers FastAPI, repositorios SQLAlchemy, `QdrantStore`, `OllamaEmbedder`, `FernetSecretEncryptor`, etc.

Los casos de uso no conocen SQLAlchemy ni Qdrant directamente: dependen de
`Protocol`s definidos en `domain/ports/`, y es `infrastructure/` quien los
implementa. Esto permite testear el dominio sin Docker (~730 tests unitarios,
ver [Tests](#tests)) y sustituir adaptadores (p. ej. otro vector store) sin
tocar la lógica de negocio. Detalle del layout de paquetes en
[`backend/README.md`](backend/README.md).

---

## Requisitos previos

- **Python 3.12** exacto (`pyproject.toml` exige `>=3.12`, pero `setup.sh` solo
  ha sido probado con 3.12 — 3.13 no está verificado).
- **Docker** + **plugin `docker compose`** (no el viejo `docker-compose` con
  guión). En WSL2: Docker Desktop → Settings → Resources → WSL Integration.
- **Node 20+** y **npm** (opcional — sin ellos, `setup.sh` monta solo el
  backend y avisa).
- **~10 GB de disco libre**: imágenes Docker (Postgres, Qdrant, MySQL, Ollama)
  + los modelos que Ollama pre-pulla (`bge-m3` ~1.2 GB, `llama3.1` ~4.7 GB).
  Cifras orientativas — varían por plataforma.
- Linux / macOS / WSL2. Windows nativo no está soportado (`setup.sh` es bash).

---

## Quickstart

```bash
git clone <repo-url> rag-chatbot-platform
cd rag-chatbot-platform
bash scripts/setup.sh
```

`scripts/setup.sh` es **idempotente** (reejecutable sin romper nada) y deja
todo listo: comprueba prerequisitos, crea `infra/.env` con secretos
aleatorios, levanta Postgres/Qdrant/MySQL/Ollama, aplica migraciones,
corre la suite unitaria como smoke check e instala las dependencias del
frontend. Ver [Configuración](#configuración) si algo falla.

Luego, arranca ambos servicios y sigue el flujo guiado:

```bash
bash scripts/dev.sh          # backend en :8000, frontend en :3000
```

1. Abre **http://localhost:3000** → **Registrarse** (crea cuenta + tenant).
2. **Knowledge Bases → Nueva KB** → elige un proveedor de embeddings (Ollama
   `bge-m3` no cuesta nada, ya viene pre-pulled por `setup.sh`).
3. Dentro de la KB, **sube un PDF/TXT** y espera a que la ingestión pase a
   `done` (barra de progreso en vivo).
4. **Chatbots → Nuevo chatbot** → vincúlalo a la KB y elige un modelo de
   generación (Ollama `llama3.1`, o una credencial OpenAI-compatible propia).
5. **Playground** del chatbot → pregunta sobre el documento subido → verás la
   respuesta con citas al contexto recuperado.
6. **Chatbots → \<tu bot\> → Widget** → copia el snippet (`<script src=".../widget/widget.js" data-public-key="...">`)
   y pégalo en cualquier HTML para embeberlo fuera de la plataforma.

> **Nota sobre el chat en `next dev`:** el proxy de `next dev` corta las
> peticiones upstream a ~30s; el chat con un LLM lento en CPU puede tardar
> varios minutos y fallar a través de él. Las peticiones cortas (login,
> listados, ingestión) funcionan bien. Para probar el chat end-to-end usa el
> deploy de producción (`infra/docker-compose.prod.yml`), cuyo nginx enruta
> `/api` **directo al backend** con timeouts largos (ver [Deploy](#deploy-producción)).

---

## Configuración

Todas las variables viven en [`infra/.env.example`](infra/.env.example)
(plantilla que `scripts/setup.sh` copia a `infra/.env`). Las más relevantes:

| Variable | Para qué | Default relevante |
|---|---|---|
| `POSTGRES_URL` | Conexión a Postgres (datos de la app) | hostname `postgres` (docker) / `localhost` (uvicorn local) |
| `QDRANT_URL` | Conexión al vector store | `http://qdrant:6333` |
| `OLLAMA_BASE_URL` | Servidor Ollama para inferencia local gratis | `http://ollama:11434` |
| `JWT_SECRET` / `FERNET_KEY` | Firma de tokens / cifrado de API keys de tenant | generados aleatorios por `setup.sh` — **nunca** dejar el placeholder |
| `COOKIE_SECURE` | Flag `Secure` en la cookie de auth httpOnly | `false` en dev, `true` en prod (HTTPS) |
| `FRONTEND_ORIGIN` | CORS a nivel de app — origen permitido | `http://localhost:3000` en dev; en prod, el origen público real |
| `STORAGE_LOCAL_PATH` | Carpeta de subidas (backend local storage) | `/data/storage` (requiere root); `setup.sh` lo sobreescribe a `/tmp/tfm_rag_storage` en dev |
| `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` | Credenciales del servicio `mysql_source` — una **fuente SQL de demo** (independiente de Postgres) para probar chatbots con datos tabulares y para los datasets de evaluación con escenario SQL | ver `infra/.env.example` |
| `RATE_LIMIT_REDIS_URL` | Backend Redis opcional para rate-limiting del widget público | sin fijar → rate-limit deshabilitado |
| `EVAL_MYSQL_*`, `RAGAS_*`, `OPENAI_API_KEY` | Aprovisionamiento de esquemas MySQL por dataset + tuning del juez RAGAS | ver sección [Evaluación](#evaluación) |

**`RUN_MIGRATIONS`** no vive en `.env.example` — es una variable de entorno
del **contenedor backend** (`backend/docker-entrypoint.sh`), no de la app.
Controla si el contenedor aplica `alembic upgrade head` al arrancar:

```bash
RUN_MIGRATIONS=1   # default — aplica migraciones pendientes antes de uvicorn
RUN_MIGRATIONS=0   # las migraciones se aplican fuera de banda (p. ej. paso previo en CI/CD)
```

Ver [Deploy](#deploy-producción) para cómo se usa en producción.

---

## Deploy (producción)

`infra/docker-compose.prod.yml` levanta el stack completo same-origin tras
nginx: **nginx → Next.js (`web`) → FastAPI (`backend`)** + Postgres + Qdrant
(+ MySQL de demo, opcional).

```bash
cd infra
cp .env.example .env   # y rellena JWT_SECRET, FERNET_KEY, OAuth, etc. — nunca placeholders
docker compose -f docker-compose.prod.yml up -d --build
# nginx publica la app en :80
```

El servicio `mysql_source` (fuente SQL de demo) **no** se levanta por
defecto en prod — está detrás de un profile porque no es parte de un deploy
real, solo sirve para demostrar el conector SQL:

```bash
docker compose -f docker-compose.prod.yml --profile demo up -d
```

Detalles del routing y arranque:

- El contenedor `backend` aplica migraciones automáticamente al arrancar
  (`RUN_MIGRATIONS=1` por defecto, ver [Configuración](#configuración)) — un
  deploy desde Postgres vacío queda con el esquema al día sin pasos manuales.
- **nginx** sirve la SPA de Next en `/` y enruta `/api` + `/widget` **directo
  al backend** (no a través de Next), con `proxy_read/send_timeout 600s` para
  que el chat (LLM lento en CPU) no se corte — evita el cap de ~30s del proxy
  de `next dev`.
- **`BACKEND_URL` se hornea a build-time** en la imagen de Next
  (`output: standalone` no re-lee `next.config.js` en runtime). Se pasa como
  `build.args` en el compose (`BACKEND_URL=http://backend:8000`), no como
  variable de entorno de runtime.
- `COOKIE_SECURE=true` en prod — la cookie de auth solo viaja por HTTPS.
- La imagen del backend es **multi-stage y corre como usuario no-root**
  (`backend/Dockerfile`): un stage `builder` compila las deps con toolchain
  de C, y el runtime final solo copia el venv ya construido.

---

## Desarrollo

### Tests

```bash
cd backend
source .venv/bin/activate

# Variables que la API + alembic + tests esperan (los unit las ignoran salvo
# arranque del import; los integration sí las necesitan):
export POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag'
export QDRANT_URL='http://localhost:6333'
export OLLAMA_BASE_URL='http://localhost:11434'
export JWT_SECRET=$(grep '^JWT_SECRET=' ../infra/.env | cut -d= -f2-)
export FERNET_KEY=$(grep '^FERNET_KEY=' ../infra/.env | cut -d= -f2-)
export STORAGE_LOCAL_PATH=/tmp/tfm_rag_storage

# Unitarios — ~730 tests en 130 ficheros, no requieren Docker, rápidos.
pytest tests/ -m "not integration"

# Lint + tipos
ruff check .
mypy src/

# Cobertura (mismo gate que corre en pre-commit vía scripts/coverage.sh)
bash ../scripts/coverage.sh
```

> **⚠️ Integration tests (~78 tests en 35 ficheros) TRUNCAN la base de datos
> con la que corren.** Están gateados detrás de `TFM_RUN_INTEGRATION=1` — sin
> esa variable, `pytest` los **salta** aunque los selecciones explícitamente,
> precisamente para que no borres tu BD de desarrollo sin querer:
>
> ```bash
> TFM_RUN_INTEGRATION=1 pytest tests/integration -m integration -v
> ```
>
> Requieren el stack Docker arriba (`docker compose up -d` en `infra/`) y
> migraciones aplicadas. No los corras contra una BD con datos que te
> importen.

**E2E (Playwright)** — 14 specs / ~48 escenarios, contra un mirror nginx
local que levanta el propio harness:

```bash
bash scripts/e2e.sh                 # todos los proyectos
bash scripts/e2e.sh --project=fast  # specs rápidas, sin LLM
bash scripts/e2e.sh --project=llm   # chat/ingest/eval/journeys (lentos, en serie)
```

**Frontend (Vitest + Testing Library)**:

```bash
cd frontend && npm test
```

### Estructura del repositorio

```
.
├── backend/                       FastAPI app (toda la lógica)
│   ├── src/tfm_rag/
│   │   ├── domain/                Entidades, value objects, errores, puertos (Protocol)
│   │   ├── application/           Casos de uso (auth, integrations, knowledge, chat, eval)
│   │   └── infrastructure/        Adaptadores: persistence, api, jobs, storage,
│   │                              document_loaders, chunkers, embedders,
│   │                              vector_store, secrets, rerankers
│   ├── alembic/versions/          Migraciones (0001…0024+)
│   ├── tests/
│   │   ├── unit/                  ~730 tests, 130 ficheros. No requieren Docker.
│   │   └── integration/           ~78 tests, 35 ficheros. Requieren stack viva + TFM_RUN_INTEGRATION=1.
│   ├── pyproject.toml             Deps + [dev] + [eval]
│   ├── Dockerfile                 Multi-stage, runtime no-root
│   └── README.md                  Detalles internos del backend (layout, patrones, settings)
│
├── frontend/                      Next.js App Router
│   ├── app/                       1 carpeta por ruta; middleware auth-gate por cookie httpOnly
│   ├── src/
│   │   ├── components/            ui/ (shadcn) + layout/ + features/
│   │   ├── lib/                   api.ts, auth.tsx, queries.ts, i18n.ts
│   │   └── types/                 Tipos del API
│   ├── Dockerfile                 Build standalone (node:20-alpine)
│   └── package.json
│
├── widget/                        Widget JS embebible (sin build step)
│
├── infra/
│   ├── docker-compose.yml         Postgres + Qdrant + MySQL + Ollama (dev)
│   ├── docker-compose.prod.yml    + nginx + Next — mysql_source detrás de --profile demo
│   ├── nginx/                     Config de nginx (prod + mirror de e2e)
│   ├── .env.example               Plantilla — copiada a .env por setup.sh
│   └── seed/ollama_pull.sh        Pre-pulla bge-m3 + llama3.1 al arrancar Ollama
│
├── eval/
│   ├── testing-datasets/          Datasets curados (world-countries, ergohaus-furniture):
│   │                              docs + seed.sql + rows.jsonl, cada uno con su propio README
│   ├── schema.json                Schema legado (usado por scripts/validate-dataset.py)
│   └── seeds/, seed-docs/         Material fuente para construir datasets
│
├── e2e/                           Suite Playwright (specs en tests/areas/)
│
├── docs/
│   ├── DOMAIN-INFERENCE-MAP.md         Modelo de dominio de proveedores/credenciales/modelos
│   └── EVAL-CAMPAIGN-WALKTHROUGH.md    Cómo funciona la campaña de evaluación RAGAS paso a paso
│
├── scripts/                       Ver tabla de scripts más abajo
│
└── README.md                      Este fichero
```

### Scripts

| Script | Qué hace |
|---|---|
| `scripts/setup.sh` | Bootstrap idempotente en un equipo nuevo: prerequisitos, venv `[dev,eval]`, `.env` con secretos aleatorios, docker compose up, migraciones, smoke test, `npm install`. |
| `scripts/dev.sh` | Arranca backend + frontend juntos (o por separado con `--backend-only`/`--frontend-only`). |
| `scripts/run-backend.sh` | Arranca uvicorn con las env vars correctas contra el stack Docker ya levantado. |
| `scripts/run-frontend.sh` | Arranca el dev server de Next.js con rewrites `/api` + `/widget` al backend. |
| `scripts/start-bg.sh` | Arranca infra + backend + frontend en background, logs en `scripts/logs/`. |
| `scripts/stop-bg.sh` | Para los procesos backend/frontend lanzados por `start-bg.sh`. |
| `scripts/e2e.sh` | Lanza la suite Playwright (`--project=fast`/`--project=llm`/`--list`). |
| `scripts/verify.sh` | Preflight ruidoso (verifica cada dependencia con ✓/✗) + smoke E2E rápido. |
| `scripts/coverage.sh` | `pytest` con gate de cobertura ≥80% sobre `domain`+`application`; HTML en `docs/coverage/`. |
| `scripts/grant-superadmin.sh` | Concede o revoca el rol superadmin a un usuario por email (solo DB-seed, sin API). |
| `scripts/init-debug.sh` | Inicializa el sistema end-to-end (usuario + KB + chatbot) para depuración/demos manuales. |
| `scripts/seed-chatbot.sh` | Crea una instancia completa de chatbot vía API (KB + docs + ingestión + chat de prueba). |
| `scripts/validate-dataset.py` | Valida un dataset JSONL en el formato legado contra `eval/schema.json`. |
| `scripts/validate-testing-dataset.py` | Valida un *testing dataset* (formato actual `eval/testing-datasets/<name>/`) end-to-end sin Docker. |
| `scripts/verify-sql-references.py` | Ejecuta el `sql_reference` de cada fila de un dataset contra el MySQL sembrado y clasifica PASS/EMPTY/FAIL. |
| `scripts/score-execution-accuracy.py` | Añade `execution_accuracy` a un `report.json` re-ejecutando SQL generado vs. de referencia. |
| `scripts/eval-report-stats.py` | Calcula ICs bootstrap 95% por métrica + latencia media por pregunta de un `report.json`. |

---

## Evaluación

El panel **`/admin/eval`** del frontend evalúa el pipeline RAG agéntico
completo (routing docs/SQL/ambos + retrieval + síntesis) contra un dataset
de preguntas con `ground_truth`, puntuado con **RAGAS** (LLM-as-judge) +
métricas deterministas (`routing_accuracy`, `abstain_accuracy`).

Datasets curados y listos para importar en **`eval/testing-datasets/`**:

- **`world-countries`** — artículos de Wikipedia en español + una BD MySQL
  relacionada (países/ciudades); preguntas de los 4 escenarios (`doc_only`,
  `sql_only`, `mixed`, `abstain`). Ver su
  [README](eval/testing-datasets/world-countries/README.md) para el desglose
  exacto de preguntas.
- **`ergohaus-furniture`** — dominio ficticio de mobiliario de oficina
  (catálogo + políticas + BD transaccional). Ver su
  [README](eval/testing-datasets/ergohaus-furniture/README.md).

Flujo (detallado paso a paso, con qué modelo actúa dónde y qué cuesta, en
[`docs/EVAL-CAMPAIGN-WALKTHROUGH.md`](docs/EVAL-CAMPAIGN-WALKTHROUGH.md)):

1. **Datasets** tab → nuevo dataset → sube `docs/*` + `seed.sql` → **Process**
   (indexa documentos + aprovisiona un esquema MySQL aislado) → **Import**
   el `rows.jsonl`.
2. **Launch** tab → elige dataset + chatbot + modelo juez → opcionalmente
   **Calibrate** para una proyección de coste → **Launch** → progreso y coste
   en vivo, cancelable.
3. **Results** → informe puntuado por pregunta y por escenario, con IC
   bootstrap 95% (calculable también offline con
   `python scripts/eval-report-stats.py backend/eval_runs/<run>/report.json`).

**Nota de coste:** solo se paga por los modelos de **generación** y el
**juez**; los embeddings (retrieval) y el juez de corrección inline corren en
Ollama local, sin coste.

---

## Terminal walkthrough (API cruda, sin frontend)

Reproduce el flujo de ingestión de documentos end-to-end por curl —
equivalente al integration test `test_doc_ingestion_flow.py`:

```bash
# 1. Health
curl -s http://localhost:8000/health | jq

# 2. Registrarse → access_token + tenant_id + credencial Ollama por defecto
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","password":"correctpassword"}' | jq -r .access_token)

# 3. Encontrar la credencial Ollama por defecto
CRED_ID=$(curl -s http://localhost:8000/api/credentials \
  -H "Authorization: Bearer $TOKEN" | jq -r '.[] | select(.provider_id=="ollama") | .id')

# 4. Crear una KnowledgeBase con embeddings Ollama bge-m3 (1024 dims)
KB_ID=$(curl -s -X POST http://localhost:8000/api/knowledge-bases \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{
        \"name\": \"Manuales\",
        \"embedding_selection\": {
          \"credential_id\": \"$CRED_ID\",
          \"model_id\": \"bge-m3\",
          \"dim\": 1024
        }
      }" | jq -r .id)

# 5. Subir un .txt y disparar la ingestión
echo "Lorem ipsum dolor sit amet." > /tmp/sample.txt
JOB_ID=$(curl -s -X POST "http://localhost:8000/api/knowledge-bases/$KB_ID/sources/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/sample.txt;type=text/plain" | jq -r .job_id)

# 6. Polling — status pasa de queued → running → done con progress 0→100
watch -n 1 "curl -s http://localhost:8000/api/ingestion-jobs/$JOB_ID -H 'Authorization: Bearer $TOKEN' | jq"
```

Swagger UI en `http://localhost:8000/docs` (botón "Authorize" para meter el
Bearer token) es la forma más cómoda de explorar el resto de endpoints
(chatbots, sesiones de chat, evaluación, admin).

---

## Operaciones comunes

### Resetear el estado de la BD (perder todos los datos)

```bash
cd infra
docker compose down -v          # -v borra también los volúmenes (datos persistentes)
bash ../scripts/setup.sh        # vuelve a montar todo desde cero
```

### Ver logs de los servicios

```bash
cd infra
docker compose logs -f ollama   # o postgres / qdrant / mysql_source
```

### Ver qué hay dentro de Postgres / Qdrant

```bash
docker exec -it tfm-rag-postgres-1 psql -U tfm -d tfm_rag
# \dt                              listar tablas
# SELECT id, email, tenant_id FROM users;

curl -s http://localhost:6333/collections | jq
```

---

## Troubleshooting

### `setup.sh` falla con "WSL2 detected but docker info failed"
Abre Docker Desktop → Settings → Resources → WSL Integration, marca tu
distribución de WSL2 y aplica. Cierra y vuelve a abrir la terminal.

### Ollama dual / embeddings dan timeout o "no embedding"
Es posible tener un Ollama *nativo* del host **y** el container
`tfm-rag-ollama-1` peleándose por el puerto 11434:

```bash
curl -s http://localhost:11434/api/tags | jq '.models[].name'
```

Si no aparece `bge-m3`, para el Ollama del host (`systemctl --user stop
ollama` en Linux, o cierra la app en macOS) o pulla el modelo en la
instancia que sí está activa.

### `STORAGE_LOCAL_PATH=/data/storage` permission denied
El default de `.env.example` apunta a `/data/storage`, que requiere root.
`setup.sh` ya lo sobreescribe a `/tmp/tfm_rag_storage` en dev. Si corres algo
a mano y ves esto:

```bash
export STORAGE_LOCAL_PATH=/tmp/tfm_rag_storage
mkdir -p $STORAGE_LOCAL_PATH
```

### `pip install` muy lento o falla en la red
Algunas deps son pesadas (`qdrant-client`, `pypdf`, `httpx`, `ragas`). En
WSL2 a veces ayuda `pip config set global.index-url https://pypi.org/simple`
y comprobar que la fecha del sistema está sincronizada.

### Corrí `pytest tests/integration` sin querer y me borró datos de dev
Es el comportamiento esperado del gate: sin `TFM_RUN_INTEGRATION=1` los
tests de integración se **saltan** (no corren), así que si de verdad
perdiste datos fue con la variable puesta contra una BD que no era
desechable. Reconstruye con `docker compose down -v && bash scripts/setup.sh`.

---

## Licencia

El código original de este proyecto se distribuye bajo la **GNU Affero General Public License v3.0 (AGPL-3.0)**. Ver [`LICENSE`](LICENSE).

Las bibliotecas y dependencias de terceros que el proyecto integra (FastAPI, SQLAlchemy, el cliente de Qdrant, Next.js y el resto de paquetes declarados en `backend/pyproject.toml` y `frontend/package.json`) conservan sus respectivas licencias, indicadas en cada paquete. Publicar este repositorio bajo AGPL-3.0 no altera las licencias de esas dependencias.
