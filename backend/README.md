# tfm-rag-backend

Backend de la plataforma RAG. FastAPI + SQLAlchemy 2.x async + Alembic
+ pydantic 2.

**Para instalar y arrancar todo (incluida la infra y la app):** ver
[`../README.md`](../README.md) en la raíz del repo. Este fichero solo cubre
detalles **internos** del backend.

---

## Layout

```
src/tfm_rag/
├── domain/                Lógica pura. Sin imports de FastAPI, SQLAlchemy, etc.
│   ├── entities/          User, Tenant, ProviderCredential, KnowledgeBase, Source, IngestionJob
│   ├── value_objects/     ChunkingConfig, EmbeddingSelection
│   ├── errors/            DomainError jerarquía (common, auth, integrations, knowledge)
│   ├── ports/             Protocols: Storage, DocumentLoader, Chunker, Embedder,
│   │                      SecretEncryptor, OAuthVerifier, SourceConnectionTester
│   └── catalog/           Catálogos en-código: LLM_PROVIDER_CATALOG, EMBEDDING_PROVIDER_CATALOG
│
├── application/           Use cases (orquestación). Cada caso de uso es un módulo.
│   ├── auth/              register_user, login_user, login_with_google, bootstrap_tenant
│   ├── integrations/      upsert_provider_credential, list_credentials, delete_credential, test_credential
│   └── knowledge/         CRUD de KB, ops de Source, AttachDocumentSource, IngestSource, ReindexSource, GetIngestionJob
│
└── infrastructure/        Adaptadores concretos (todo lo "sucio").
    ├── api/
    │   ├── app.py             create_app() — monta routers + middleware
    │   ├── dependencies.py    get_session, get_current_context
    │   ├── middleware/        TenantScopingMiddleware (extrae JWT → RequestContext)
    │   └── routers/           auth, credentials, health, knowledge_bases, ingestion_jobs
    ├── persistence/
    │   ├── base.py            Base declarativa
    │   ├── engine.py          build_engine, build_session_factory, session_scope
    │   ├── repository.py      BaseRepository genérico (tenant-scoped)
    │   ├── models/            ORM: tenants, users, provider_credentials, knowledge_bases, sources, ingestion_jobs
    │   └── repositories/      Por modelo, hereda BaseRepository
    ├── auth/                  JWT (jose) + bcrypt + Google OAuth verifier
    ├── secrets/               FernetSecretEncryptor (cifra api_keys de tenant)
    ├── jobs/                  JobsRunner (wrapper de BackgroundTasks + InMemoryRunner para tests)
    ├── storage/               LocalStorage (file://) — file uploads
    ├── document_loaders/      PdfLoader, TxtLoader, LoaderDispatcher (by-mime)
    ├── chunkers/              FixedSizeChunker (sliding window con overlap)
    ├── embedders/             OllamaEmbedder
    └── vector_store/          QdrantStore (ensure_collection, upsert_points, delete_by_source)
```

Patrones del repo:
- Use cases reciben `session` + `RequestContext` + colaboradores explícitos.
- Repos heredan `BaseRepository[Row]` que añade `tenant_id` a todas las queries.
- Errores de dominio (`DomainError`/`NotFoundError`/...) los traducen los routers a HTTP status codes.
- Routers son delgados: validan input con Pydantic, llaman al use case, mapean errores a `HTTPException`.

## Migraciones

```bash
# Ver estado actual
alembic current
alembic heads

# Aplicar
alembic upgrade head

# Crear una nueva (asumiendo branch limpia y modelos registrados en alembic/env.py)
alembic revision -m "add foo"
```

Las migraciones se nombran `0001_baseline.py`, `0002_..`, `0003_..`. El down_revision
encadena en orden — no usar autogenerate alegremente, escribirlas a mano para
mantenerlas auditables.

## Tests

```bash
# Asume venv activa + variables exportadas (ver ../README.md "Arrancar el backend")
pytest tests/ -m "not integration"      # unit, sin Docker
pytest tests/integration -m integration # con Docker arriba
pytest tests/path/to/test.py -v -k name # uno solo
```

Convenciones:
- Marker `@pytest.mark.integration` para los que necesitan Postgres/Qdrant/Ollama vivos.
- `tests/conftest.py` mete env vars por defecto **antes** de importar tfm_rag (porque
  `Settings` valida al cargar). No la borres.
- Mocks de repos en unit tests vía `MagicMock` + `AsyncMock`. Patrón consolidado.
- `func.__test__ = False` en use cases cuyo nombre empieza por `test_` (porque el
  spec dice `TestX` → snake_case `test_x`) y son importados desde el test file. Si
  no, pytest los colecciona como tests.

## Lint + tipos

```bash
ruff check .
ruff check . --fix          # autofix import order + unused imports + etc.
mypy src/
```

`ruff.toml` y `mypy.ini` tienen la configuración.

## Settings

`infrastructure/settings.py` lee de `.env` en el CWD. Para uvicorn local apunta a
`localhost`. Para el container backend (compose) usa hostnames (`postgres`,
`qdrant`, `ollama`). El `STORAGE_LOCAL_PATH` por defecto es `/data/storage`
(requiere root); en dev override a `/tmp/tfm_rag_storage`.

## Background tasks

- `JobsRunner(background_tasks)` envuelve `FastAPI BackgroundTasks` y captura
  excepciones (las loguea en lugar de tragárselas).
- Una tarea background **abre su propia sesión** porque la sesión del request
  se cierra al enviar la respuesta. Patrón visto en `_ingest_in_background`
  (`routers/knowledge_bases.py`).
- Endpoints que crean filas pre-background deben `await session.commit()` (no
  `flush()`) antes de programar la tarea, o el background no las verá.
