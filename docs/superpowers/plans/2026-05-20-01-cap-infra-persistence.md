# CAP-INFRA-PERSISTENCE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lay the foundational data layer — Postgres + SQLAlchemy async + Alembic + Qdrant client + docker-compose with Ollama — on which all other CAPs depend.

**Architecture:** Hexagonal. Domain layer unaware of persistence. Repository pattern with async SQLAlchemy. Qdrant collections per `(tenant, dim)` created on-demand. `docker-compose.yml` orchestrates Postgres + Qdrant + Ollama as required services with healthchecks. Backend exposes a `/health` endpoint that probes all three.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async + asyncpg, Alembic, Pydantic Settings v2, qdrant-client (async), httpx, pytest + pytest-asyncio + testcontainers, ruff, mypy, Docker Compose.

---

## Master roadmap (17 plans, dependency order)

This is plan **#1 of 17**. The other 16 will be written using the same template after this one is implemented and merged.

| # | CAP | Depends on | Layer |
|---|---|---|---|
| 01 | `CAP-INFRA-PERSISTENCE` | — | Plataforma |
| 02 | `CAP-INFRA-TENANT-ISOLATION` | 01 | Plataforma |
| 03 | `CAP-INFRA-SECRETS` | 01 | Plataforma |
| 04 | `CAP-INFRA-ASYNC-JOBS` | 01, 02 | Plataforma |
| 05 | `CAP-AUTH-IDENTITY` | 01, 02, 03 | Plataforma |
| 06 | `CAP-INTEG-CREDENTIALS` | 03, 02 | Plataforma |
| 07 | `CAP-KB-LIFECYCLE` | 01, 02, 06 | Definición |
| 08 | `CAP-KB-DOC-SOURCES` | 07, 04, 06 | Definición |
| 09 | `CAP-KB-DB-SOURCES` | 07, 03, 02 | Definición |
| 10 | `CAP-CHATBOT-LIFECYCLE` | 07, 06 | Definición |
| 11 | `CAP-CHATBOT-WIDGET-CONFIG` | 10 | Definición |
| 12 | `CAP-CHAT-DOC-RETRIEVAL` | 07, 06, 01, 02 | Runtime |
| 13 | `CAP-CHAT-SQL-EXECUTION` | 09, 06, 03, 02 | Runtime |
| 14 | `CAP-CHAT-SESSIONS` | 01, 02, 10 | Runtime |
| 15 | `CAP-CHAT-AGENT-LOOP` | 12, 13, 14, 06 | Runtime |
| 16 | `CAP-WIDGET-RUNTIME` | 11, 15, 02 | Runtime |
| 17 | `CAP-EVAL-RAGAS` | 15, 10, 06 | Evaluación |

Roadmap recommendation per user (P-01): implement in M1 → M2 → M3 → M4 → M6 → M5 → M7 order. This means plans 01–06 (M1) first, then 07–08 (M2), then 10+11+14+15 (M3), then 09+13+rest of 15 (M4), then 17 (M6 — RAGAS), then 16 (M5 — widget), then polish.

Source of truth for design decisions: `docs/superpowers/specs/2026-05-19-tfm-roadmap-funcional-design.html`. Decisions log: `conversation-2026-05-19.log`.

---

## File structure for this plan

**Created:**

```
backend/
├── pyproject.toml
├── ruff.toml
├── mypy.ini
├── pytest.ini
├── README.md
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 0001_baseline.py
├── src/
│   └── tfm_rag/
│       ├── __init__.py
│       ├── domain/
│       │   ├── __init__.py
│       │   └── errors/
│       │       ├── __init__.py
│       │       └── common.py
│       ├── infrastructure/
│       │   ├── __init__.py
│       │   ├── settings.py
│       │   ├── persistence/
│       │   │   ├── __init__.py
│       │   │   ├── engine.py
│       │   │   ├── base.py
│       │   │   └── repository.py
│       │   ├── vector_store/
│       │   │   ├── __init__.py
│       │   │   └── qdrant_client.py
│       │   └── api/
│       │       ├── __init__.py
│       │       ├── app.py
│       │       └── routers/
│       │           ├── __init__.py
│       │           └── health.py
│       └── cli/
│           └── __init__.py
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── unit/
    │   ├── __init__.py
    │   ├── test_settings.py
    │   ├── test_repository_base.py
    │   └── test_qdrant_client.py
    └── integration/
        ├── __init__.py
        ├── test_alembic_baseline.py
        └── test_health_endpoint.py

infra/
├── docker-compose.yml
├── docker-compose.eval.yml
├── .env.example
└── seed/
    └── ollama_pull.sh

.gitignore
```

**Responsibilities:**
- `backend/pyproject.toml`: package metadata, dependencies pinned (see §5 of spec).
- `backend/src/tfm_rag/infrastructure/settings.py`: Pydantic Settings loading from `.env` — single source for env vars.
- `backend/src/tfm_rag/infrastructure/persistence/engine.py`: async SQLAlchemy engine + session factory.
- `backend/src/tfm_rag/infrastructure/persistence/base.py`: `DeclarativeBase` for SQLAlchemy models (no tables yet — added in plan 02+).
- `backend/src/tfm_rag/infrastructure/persistence/repository.py`: generic `BaseRepository[E]` with tenant-aware filtering (interface only — actual tenant filter activated in plan 02).
- `backend/src/tfm_rag/infrastructure/vector_store/qdrant_client.py`: thin async wrapper exposing `ensure_collection(tenant_id, dim)` and a health-check method.
- `backend/src/tfm_rag/infrastructure/api/app.py`: FastAPI app factory.
- `backend/src/tfm_rag/infrastructure/api/routers/health.py`: `/health` endpoint probing Postgres + Qdrant + Ollama.
- `backend/alembic/`: migrations folder, baseline only (real tables come in later plans).
- `infra/docker-compose.yml`: stack with Postgres + Qdrant + Ollama + backend, healthchecks, depends_on with `condition: service_healthy`.
- `infra/seed/ollama_pull.sh`: post-startup script that pulls `llama3.1` and `bge-m3` if not present.

---

## Task 1 — Project skeleton + tooling

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/ruff.toml`
- Create: `backend/mypy.ini`
- Create: `backend/pytest.ini`
- Create: `backend/src/tfm_rag/__init__.py` (empty)
- Create: `backend/tests/__init__.py` (empty)
- Create: `.gitignore`

- [ ] **Step 1.1: Create `.gitignore` at repo root**

```
# Python
__pycache__/
*.py[cod]
*$py.class
.venv/
venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.egg-info/
dist/
build/

# Env
.env
*.local

# IDE
.vscode/
.idea/
*.swp

# Data
backend/data/
storage/
qdrant_data/
postgres_data/
```

- [ ] **Step 1.2: Create `backend/pyproject.toml`**

```toml
[project]
name = "tfm-rag-backend"
version = "0.1.0"
description = "TFM RAG Chatbot Platform — backend"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "sqlalchemy[asyncio]>=2.0.36",
    "alembic>=1.14",
    "asyncpg>=0.30",
    "qdrant-client>=1.12",
    "httpx>=0.28",
    "structlog>=24.4",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-cov>=6.0",
    "testcontainers>=4.8",
    "ruff>=0.8",
    "mypy>=1.13",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tfm_rag"]
```

- [ ] **Step 1.3: Create `backend/ruff.toml`**

```toml
line-length = 100
target-version = "py312"

[lint]
select = ["E", "F", "I", "B", "UP", "ASYNC", "S", "N"]
ignore = ["S101"]  # allow assert in tests

[lint.per-file-ignores]
"tests/**/*.py" = ["S"]
```

- [ ] **Step 1.4: Create `backend/mypy.ini`**

```ini
[mypy]
python_version = 3.12
strict = True
plugins = pydantic.mypy
warn_unused_configs = True
ignore_missing_imports = True

[mypy-tests.*]
disallow_untyped_defs = False
```

- [ ] **Step 1.5: Create `backend/pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
addopts = -ra -q --strict-markers
markers =
    integration: requires docker-compose services running
```

- [ ] **Step 1.6: Create empty package files**

Run from `backend/`:

```bash
mkdir -p src/tfm_rag/domain/errors \
         src/tfm_rag/infrastructure/persistence \
         src/tfm_rag/infrastructure/vector_store \
         src/tfm_rag/infrastructure/api/routers \
         src/tfm_rag/cli \
         tests/unit tests/integration
touch src/tfm_rag/__init__.py \
      src/tfm_rag/domain/__init__.py \
      src/tfm_rag/domain/errors/__init__.py \
      src/tfm_rag/infrastructure/__init__.py \
      src/tfm_rag/infrastructure/persistence/__init__.py \
      src/tfm_rag/infrastructure/vector_store/__init__.py \
      src/tfm_rag/infrastructure/api/__init__.py \
      src/tfm_rag/infrastructure/api/routers/__init__.py \
      src/tfm_rag/cli/__init__.py \
      tests/__init__.py \
      tests/unit/__init__.py \
      tests/integration/__init__.py
```

- [ ] **Step 1.7: Install and verify**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate    # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
ruff check .
mypy src/
```
Expected: no errors (empty modules).

- [ ] **Step 1.8: Commit**

```bash
git add .gitignore backend/
git commit -m "feat(infra): bootstrap backend skeleton with tooling"
```

---

## Task 2 — Pydantic Settings + `.env.example`

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/settings.py`
- Create: `infra/.env.example`
- Create: `backend/tests/unit/test_settings.py`

- [ ] **Step 2.1: Write the failing test**

`backend/tests/unit/test_settings.py`:

```python
import os
import pytest
from tfm_rag.infrastructure.settings import Settings


def test_settings_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://u:p@h:5432/d")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("FERNET_KEY", "X4O7zPlk-AbCdEfGhIjKlMnOpQrStUvWxYz0123456=")

    s = Settings()  # type: ignore[call-arg]

    assert s.postgres_url == "postgresql+asyncpg://u:p@h:5432/d"
    assert s.qdrant_url == "http://qdrant:6333"
    assert s.ollama_base_url == "http://ollama:11434"
    assert s.jwt_expires_hours == 24
    assert s.log_level == "INFO"


def test_settings_missing_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("POSTGRES_URL", "QDRANT_URL", "OLLAMA_BASE_URL", "JWT_SECRET", "FERNET_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(Exception):  # pydantic ValidationError
        Settings()  # type: ignore[call-arg]
```

- [ ] **Step 2.2: Run test to verify it fails**

```bash
pytest tests/unit/test_settings.py -v
```
Expected: FAIL with `ImportError: cannot import name 'Settings'`.

- [ ] **Step 2.3: Implement `Settings`**

`backend/src/tfm_rag/infrastructure/settings.py`:

```python
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    postgres_url: str = Field(...)
    # Qdrant
    qdrant_url: str = Field(...)
    qdrant_api_key: str | None = None
    # Ollama
    ollama_base_url: str = Field(...)
    ollama_default_llm_model: str = "llama3.1"
    ollama_default_embedding_model: str = "bge-m3"
    # Auth
    jwt_secret: str = Field(..., min_length=32)
    jwt_expires_hours: int = 24
    fernet_key: str = Field(..., min_length=32)
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    # Storage
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_path: str = "/data/storage"
    storage_s3_bucket: str | None = None
    storage_s3_region: str | None = None
    # Misc
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    rate_limit_redis_url: str | None = None
    frontend_origin: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

- [ ] **Step 2.4: Run tests again**

```bash
pytest tests/unit/test_settings.py -v
```
Expected: PASS (2 tests).

- [ ] **Step 2.5: Create `infra/.env.example`**

```bash
# Postgres
POSTGRES_URL=postgresql+asyncpg://tfm:tfm@postgres:5432/tfm_rag

# Qdrant
QDRANT_URL=http://qdrant:6333
# QDRANT_API_KEY=

# Ollama
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_DEFAULT_LLM_MODEL=llama3.1
OLLAMA_DEFAULT_EMBEDDING_MODEL=bge-m3

# Auth
JWT_SECRET=replace_with_random_32_byte_string_xxxxx
JWT_EXPIRES_HOURS=24
FERNET_KEY=replace_with_fernet_key_generated_with_cryptography
# GOOGLE_OAUTH_CLIENT_ID=
# GOOGLE_OAUTH_CLIENT_SECRET=

# Storage
STORAGE_BACKEND=local
STORAGE_LOCAL_PATH=/data/storage

# Logging
LOG_LEVEL=INFO

# CORS
FRONTEND_ORIGIN=http://localhost:3000
```

- [ ] **Step 2.6: Commit**

```bash
git add backend/src/tfm_rag/infrastructure/settings.py \
        backend/tests/unit/test_settings.py \
        infra/.env.example
git commit -m "feat(infra): typed Settings loader with .env.example"
```

---

## Task 3 — SQLAlchemy async engine + base

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/persistence/engine.py`
- Create: `backend/src/tfm_rag/infrastructure/persistence/base.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/integration/test_engine.py`

- [ ] **Step 3.1: Write `base.py` (the DeclarativeBase)**

`backend/src/tfm_rag/infrastructure/persistence/base.py`:

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Root SQLAlchemy declarative base. All ORM models inherit from this."""
    pass
```

- [ ] **Step 3.2: Write the failing test for the engine factory**

`backend/tests/integration/test_engine.py`:

```python
import pytest
from sqlalchemy import text

from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings


@pytest.mark.integration
async def test_engine_connects_to_postgres(settings: Settings) -> None:
    engine = build_engine(settings.postgres_url)
    session_factory = build_session_factory(engine)

    async with session_factory() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1

    await engine.dispose()
```

- [ ] **Step 3.3: Add `conftest.py` with the `settings` fixture**

`backend/tests/conftest.py`:

```python
import os
import pytest

from tfm_rag.infrastructure.settings import Settings


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings from the running environment (.env or docker-compose env)."""
    # Defaults for local dev if not set; integration tests expect compose up
    monkeypatch.setenv(
        "POSTGRES_URL",
        os.environ.get(
            "POSTGRES_URL",
            "postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag",
        ),
    )
    monkeypatch.setenv(
        "QDRANT_URL",
        os.environ.get("QDRANT_URL", "http://localhost:6333"),
    )
    monkeypatch.setenv(
        "OLLAMA_BASE_URL",
        os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
    )
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv(
        "FERNET_KEY", "X4O7zPlk-AbCdEfGhIjKlMnOpQrStUvWxYz0123456="
    )
    return Settings()  # type: ignore[call-arg]
```

- [ ] **Step 3.4: Run the test (expect FAIL — no engine module yet)**

```bash
pytest tests/integration/test_engine.py -v -m integration
```
Expected: FAIL with `ImportError: cannot import name 'build_engine'`.

- [ ] **Step 3.5: Implement `engine.py`**

`backend/src/tfm_rag/infrastructure/persistence/engine.py`:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def build_engine(postgres_url: str, *, echo: bool = False) -> AsyncEngine:
    """Create an async SQLAlchemy engine. Use one per process."""
    return create_async_engine(
        postgres_url,
        echo=echo,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


def build_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Context manager that commits on success, rolls back on exception."""
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

- [ ] **Step 3.6: Re-run integration test (requires Postgres reachable)**

If docker-compose isn't up yet, skip with `-m "not integration"` or wait until Task 7. To test now, run a one-shot Postgres:

```bash
docker run --rm -d --name pg-test \
       -p 5432:5432 -e POSTGRES_USER=tfm -e POSTGRES_PASSWORD=tfm \
       -e POSTGRES_DB=tfm_rag postgres:16
sleep 3
pytest tests/integration/test_engine.py -v -m integration
docker stop pg-test
```
Expected: PASS.

- [ ] **Step 3.7: Commit**

```bash
git add backend/src/tfm_rag/infrastructure/persistence/ backend/tests/
git commit -m "feat(infra): async SQLAlchemy engine + session factory"
```

---

## Task 4 — Alembic init + baseline migration

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/0001_baseline.py`
- Create: `backend/tests/integration/test_alembic_baseline.py`

- [ ] **Step 4.1: Initialize Alembic structure**

From `backend/`:

```bash
alembic init --template async alembic
```

This generates `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/`.

- [ ] **Step 4.2: Edit `alembic.ini`**

Replace the `sqlalchemy.url` line (around line 60) with a placeholder; the real URL comes from env:

```ini
sqlalchemy.url =
```

- [ ] **Step 4.3: Edit `alembic/env.py`**

Replace the generated `env.py` with one that reads the URL from our Settings:

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

from tfm_rag.infrastructure.persistence.base import Base
from tfm_rag.infrastructure.settings import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.postgres_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

- [ ] **Step 4.4: Create the baseline migration manually**

`backend/alembic/versions/0001_baseline.py`:

```python
"""baseline

Revision ID: 0001
Revises:
Create Date: 2026-05-20 00:00:00.000000

This migration creates no tables yet — it's the empty baseline against
which all subsequent CAP migrations apply.
"""
from __future__ import annotations

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Baseline — no schema changes."""
    pass


def downgrade() -> None:
    """Baseline — no schema changes."""
    pass
```

- [ ] **Step 4.5: Write the integration test**

`backend/tests/integration/test_alembic_baseline.py`:

```python
import subprocess

import pytest
from sqlalchemy import text

from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings


@pytest.mark.integration
async def test_alembic_baseline_marks_db(settings: Settings) -> None:
    # Run migrations up to head
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd="backend",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    engine = build_engine(settings.postgres_url)
    session_factory = build_session_factory(engine)
    async with session_factory() as session:
        result = await session.execute(
            text("SELECT version_num FROM alembic_version")
        )
        version = result.scalar()
        assert version == "0001"
    await engine.dispose()
```

- [ ] **Step 4.6: Run the migration manually + test**

```bash
cd backend
# Postgres from compose or one-shot container must be running
alembic upgrade head
pytest tests/integration/test_alembic_baseline.py -v -m integration
```
Expected: PASS.

- [ ] **Step 4.7: Commit**

```bash
git add backend/alembic.ini backend/alembic/ \
        backend/tests/integration/test_alembic_baseline.py
git commit -m "feat(infra): Alembic baseline migration"
```

---

## Task 5 — Repository base class

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/persistence/repository.py`
- Create: `backend/tests/unit/test_repository_base.py`

- [ ] **Step 5.1: Write the failing test**

`backend/tests/unit/test_repository_base.py`:

```python
from uuid import UUID, uuid4

import pytest
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from tfm_rag.infrastructure.persistence.base import Base
from tfm_rag.infrastructure.persistence.repository import (
    BaseRepository,
    RequestContext,
)


class DummyEntity(Base):
    __tablename__ = "dummy_entity"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class DummyRepository(BaseRepository[DummyEntity]):
    model = DummyEntity


def test_request_context_requires_tenant_id() -> None:
    ctx = RequestContext(tenant_id=uuid4(), user_id=uuid4())
    assert ctx.tenant_id is not None
    assert ctx.user_id is not None


def test_repository_has_model() -> None:
    assert DummyRepository.model is DummyEntity
```

- [ ] **Step 5.2: Run test to confirm failure**

```bash
pytest tests/unit/test_repository_base.py -v
```
Expected: FAIL with import error.

- [ ] **Step 5.3: Implement `repository.py`**

`backend/src/tfm_rag/infrastructure/persistence/repository.py`:

```python
from dataclasses import dataclass
from typing import ClassVar, Generic, TypeVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.infrastructure.persistence.base import Base

E = TypeVar("E", bound=Base)


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Carries the authenticated tenant/user for the lifetime of a request.

    Repositories receive this and MUST filter by tenant_id on every read/write.
    The tenant filter is wired in plan 02 (CAP-INFRA-TENANT-ISOLATION); this
    class is the carrier defined in plan 01.
    """
    tenant_id: UUID
    user_id: UUID | None = None


class BaseRepository(Generic[E]):
    """Generic repository skeleton.

    Subclasses must set `model = <SQLAlchemy entity class>`. CRUD helpers
    are added in plan 02 once the tenant filter is wired.
    """
    model: ClassVar[type]  # set by subclasses to a Base-derived class

    def __init__(self, session: AsyncSession, ctx: RequestContext) -> None:
        self._session = session
        self._ctx = ctx
```

- [ ] **Step 5.4: Run test again**

```bash
pytest tests/unit/test_repository_base.py -v
```
Expected: PASS (2 tests).

- [ ] **Step 5.5: Commit**

```bash
git add backend/src/tfm_rag/infrastructure/persistence/repository.py \
        backend/tests/unit/test_repository_base.py
git commit -m "feat(infra): RequestContext + BaseRepository skeleton"
```

---

## Task 6 — Qdrant async client wrapper

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/vector_store/qdrant_client.py`
- Create: `backend/tests/unit/test_qdrant_client.py`
- Create: `backend/tests/integration/test_qdrant_health.py`

- [ ] **Step 6.1: Write the unit test (collection name derivation)**

`backend/tests/unit/test_qdrant_client.py`:

```python
from uuid import UUID

from tfm_rag.infrastructure.vector_store.qdrant_client import (
    collection_name_for,
)


def test_collection_name_derivation() -> None:
    tenant = UUID("a1b2c3d4-e5f6-7890-1234-567890abcdef")
    assert collection_name_for(tenant, dim=1024) == \
        "kb_chunks__a1b2c3d4-e5f6-7890-1234-567890abcdef__1024"


def test_collection_name_rejects_invalid_dim() -> None:
    import pytest
    tenant = UUID("a1b2c3d4-e5f6-7890-1234-567890abcdef")
    with pytest.raises(ValueError, match="dim must be positive"):
        collection_name_for(tenant, dim=0)
```

- [ ] **Step 6.2: Run unit test (expect FAIL)**

```bash
pytest tests/unit/test_qdrant_client.py -v
```
Expected: FAIL with import error.

- [ ] **Step 6.3: Implement `qdrant_client.py`**

`backend/src/tfm_rag/infrastructure/vector_store/qdrant_client.py`:

```python
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams


def collection_name_for(tenant_id: UUID, dim: int) -> str:
    """Derive the Qdrant collection name for a (tenant, dim) pair.

    See spec §9 — one physical collection per (tenant, dim).
    """
    if dim <= 0:
        raise ValueError("dim must be positive")
    return f"kb_chunks__{tenant_id}__{dim}"


class QdrantStore:
    """Thin async wrapper around AsyncQdrantClient with on-demand collections."""

    def __init__(self, url: str, api_key: str | None = None) -> None:
        self._client = AsyncQdrantClient(url=url, api_key=api_key)

    async def ensure_collection(self, tenant_id: UUID, dim: int) -> str:
        """Create the (tenant, dim) collection if it doesn't exist. Returns its name."""
        name = collection_name_for(tenant_id, dim)
        existing = {c.name for c in (await self._client.get_collections()).collections}
        if name not in existing:
            await self._client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
        return name

    async def health(self) -> bool:
        """Return True if Qdrant is reachable."""
        try:
            await self._client.get_collections()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.close()
```

- [ ] **Step 6.4: Run unit test (expect PASS)**

```bash
pytest tests/unit/test_qdrant_client.py -v
```
Expected: PASS (2 tests).

- [ ] **Step 6.5: Write the integration test**

`backend/tests/integration/test_qdrant_health.py`:

```python
from uuid import uuid4

import pytest

from tfm_rag.infrastructure.settings import Settings
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore


@pytest.mark.integration
async def test_qdrant_ensure_collection_idempotent(settings: Settings) -> None:
    store = QdrantStore(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    tenant = uuid4()
    try:
        n1 = await store.ensure_collection(tenant, dim=1024)
        n2 = await store.ensure_collection(tenant, dim=1024)
        assert n1 == n2
        assert await store.health() is True
    finally:
        # Cleanup
        await store._client.delete_collection(n1)
        await store.close()
```

- [ ] **Step 6.6: Run integration test**

Requires Qdrant up (docker-compose o `docker run --rm -d -p 6333:6333 qdrant/qdrant`):

```bash
pytest tests/integration/test_qdrant_health.py -v -m integration
```
Expected: PASS.

- [ ] **Step 6.7: Commit**

```bash
git add backend/src/tfm_rag/infrastructure/vector_store/ \
        backend/tests/unit/test_qdrant_client.py \
        backend/tests/integration/test_qdrant_health.py
git commit -m "feat(infra): Qdrant async wrapper with (tenant, dim) collections"
```

---

## Task 7 — docker-compose stack

**Files:**
- Create: `infra/docker-compose.yml`
- Create: `infra/seed/ollama_pull.sh`
- Modify: `infra/.env.example` (add `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`)

- [ ] **Step 7.1: Add Postgres init vars to `.env.example`**

Add these lines at the top of `infra/.env.example`:

```
# Postgres init (used by docker-compose)
POSTGRES_USER=tfm
POSTGRES_PASSWORD=tfm
POSTGRES_DB=tfm_rag
```

- [ ] **Step 7.2: Write `infra/docker-compose.yml`**

```yaml
name: tfm-rag

services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-tfm}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-tfm}
      POSTGRES_DB: ${POSTGRES_DB:-tfm_rag}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-tfm} -d ${POSTGRES_DB:-tfm_rag}"]
      interval: 5s
      timeout: 3s
      retries: 10

  qdrant:
    image: qdrant/qdrant:v1.12.0
    restart: unless-stopped
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage
    healthcheck:
      test: ["CMD-SHELL", "bash -c '</dev/tcp/localhost/6333'"]
      interval: 5s
      timeout: 3s
      retries: 10

  ollama:
    image: ollama/ollama:latest
    restart: unless-stopped
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
      - ./seed/ollama_pull.sh:/seed/ollama_pull.sh:ro
    entrypoint: >
      sh -c "ollama serve & sleep 3 && /seed/ollama_pull.sh && wait"
    healthcheck:
      test: ["CMD-SHELL", "ollama list >/dev/null 2>&1"]
      interval: 10s
      timeout: 5s
      retries: 20

  backend:
    build:
      context: ../backend
      dockerfile: Dockerfile
    restart: unless-stopped
    env_file:
      - .env
    environment:
      POSTGRES_URL: "postgresql+asyncpg://${POSTGRES_USER:-tfm}:${POSTGRES_PASSWORD:-tfm}@postgres:5432/${POSTGRES_DB:-tfm_rag}"
      QDRANT_URL: "http://qdrant:6333"
      OLLAMA_BASE_URL: "http://ollama:11434"
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      qdrant:
        condition: service_healthy
      ollama:
        condition: service_healthy

volumes:
  postgres_data:
  qdrant_data:
  ollama_data:
```

- [ ] **Step 7.3: Write the seed script `infra/seed/ollama_pull.sh`**

```bash
#!/bin/sh
set -e
echo "Pulling default Ollama models..."
ollama pull "${OLLAMA_DEFAULT_LLM_MODEL:-llama3.1}" || echo "WARN: failed to pull LLM model"
ollama pull "${OLLAMA_DEFAULT_EMBEDDING_MODEL:-bge-m3}" || echo "WARN: failed to pull embedding model"
echo "Ollama seed complete."
```

```bash
chmod +x infra/seed/ollama_pull.sh
```

- [ ] **Step 7.4: Write minimal `backend/Dockerfile`**

`backend/Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY . .

EXPOSE 8000

CMD ["uvicorn", "tfm_rag.infrastructure.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 7.5: Bring up the stack and verify**

```bash
cd infra
cp .env.example .env
# Generate real JWT_SECRET + FERNET_KEY now:
python -c "import secrets; print('JWT_SECRET=' + secrets.token_urlsafe(32))" >> .env
python -c "from cryptography.fernet import Fernet; print('FERNET_KEY=' + Fernet.generate_key().decode())" >> .env

docker compose up -d postgres qdrant ollama
docker compose ps
```
Expected: all 3 services healthy (Ollama may take 1-2 min for first model pull).

- [ ] **Step 7.6: Run integration tests against the stack**

```bash
cd backend
export POSTGRES_URL="postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag"
export QDRANT_URL="http://localhost:6333"
export OLLAMA_BASE_URL="http://localhost:11434"
alembic upgrade head
pytest tests/integration/ -v -m integration
```
Expected: all tests PASS.

- [ ] **Step 7.7: Commit**

```bash
git add infra/docker-compose.yml infra/seed/ infra/.env.example backend/Dockerfile
git commit -m "feat(infra): docker-compose stack with postgres+qdrant+ollama"
```

---

## Task 8 — FastAPI app + `/health` endpoint

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/api/app.py`
- Create: `backend/src/tfm_rag/infrastructure/api/routers/health.py`
- Create: `backend/tests/integration/test_health_endpoint.py`

- [ ] **Step 8.1: Implement the health router**

`backend/src/tfm_rag/infrastructure/api/routers/health.py`:

```python
from typing import Literal

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings, get_settings
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore


router = APIRouter(tags=["health"])


class ComponentHealth(BaseModel):
    name: str
    status: Literal["ok", "fail"]
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    components: list[ComponentHealth]


@router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    components: list[ComponentHealth] = []

    # Postgres
    try:
        engine = build_engine(settings.postgres_url)
        factory = build_session_factory(engine)
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        await engine.dispose()
        components.append(ComponentHealth(name="postgres", status="ok"))
    except Exception as e:
        components.append(
            ComponentHealth(name="postgres", status="fail", detail=str(e)[:200])
        )

    # Qdrant
    qdrant = QdrantStore(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    try:
        ok = await qdrant.health()
        components.append(
            ComponentHealth(name="qdrant", status="ok" if ok else "fail")
        )
    finally:
        await qdrant.close()

    # Ollama
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{settings.ollama_base_url}/api/tags")
            r.raise_for_status()
        components.append(ComponentHealth(name="ollama", status="ok"))
    except Exception as e:
        components.append(
            ComponentHealth(name="ollama", status="fail", detail=str(e)[:200])
        )

    overall = "ok" if all(c.status == "ok" for c in components) else "degraded"
    return HealthResponse(status=overall, components=components)
```

- [ ] **Step 8.2: Implement the app factory**

`backend/src/tfm_rag/infrastructure/api/app.py`:

```python
from fastapi import FastAPI

from tfm_rag.infrastructure.api.routers import health


def create_app() -> FastAPI:
    app = FastAPI(
        title="TFM RAG Chatbot Platform",
        version="0.1.0",
    )
    app.include_router(health.router)
    return app


app = create_app()
```

- [ ] **Step 8.3: Write the integration test**

`backend/tests/integration/test_health_endpoint.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient

from tfm_rag.infrastructure.api.app import app


@pytest.mark.integration
async def test_health_returns_ok_when_stack_up() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ok", "degraded"}
    names = {c["name"] for c in body["components"]}
    assert names == {"postgres", "qdrant", "ollama"}
```

- [ ] **Step 8.4: Run the test against the running stack**

```bash
pytest tests/integration/test_health_endpoint.py -v -m integration
```
Expected: PASS, all 3 components `ok`.

- [ ] **Step 8.5: Smoke-test via curl**

Run the backend locally (or via compose):

```bash
cd backend
uvicorn tfm_rag.infrastructure.api.app:app --reload --port 8000 &
sleep 2
curl -s http://localhost:8000/health | jq .
kill %1
```
Expected JSON with `status: ok` and 3 components.

- [ ] **Step 8.6: Commit**

```bash
git add backend/src/tfm_rag/infrastructure/api/ \
        backend/tests/integration/test_health_endpoint.py
git commit -m "feat(infra): FastAPI app with /health probing all 3 deps"
```

---

## Task 9 — README + closing checks

**Files:**
- Create: `backend/README.md`

- [ ] **Step 9.1: Write `backend/README.md`**

```markdown
# tfm-rag-backend — CAP-INFRA-PERSISTENCE

Backend de la plataforma RAG del TFM. Esta primera entrega cubre solo la capa de persistencia base (Postgres + Qdrant + Ollama orquestados con docker-compose) y un endpoint `/health` que verifica los tres componentes.

## Arranque

```bash
cd infra
cp .env.example .env
# Generar secretos reales
python -c "import secrets; print(secrets.token_urlsafe(32))"  # JWT_SECRET
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # FERNET_KEY
docker compose up -d
```

Espera a que los tres servicios estén `healthy` (Ollama tarda más por el pull inicial):

```bash
docker compose ps
```

Aplica las migraciones:

```bash
cd ../backend
alembic upgrade head
```

Verifica:

```bash
curl http://localhost:8000/health
```

## Tests

```bash
cd backend
pip install -e ".[dev]"
pytest tests/unit -v
# Integration tests require the stack up:
pytest tests/integration -v -m integration
```

## Próximas CAPs

Esta es la 1ª de 17 plans. Ver `docs/superpowers/plans/` para la lista completa.
```

- [ ] **Step 9.2: Run the full test suite**

```bash
cd backend
ruff check .
mypy src/
pytest tests/unit -v
pytest tests/integration -v -m integration
```
Expected: all green.

- [ ] **Step 9.3: Commit + tag**

```bash
git add backend/README.md
git commit -m "docs(infra): README for CAP-INFRA-PERSISTENCE"
git tag cap-01-infra-persistence
```

---

## Done criteria for CAP-INFRA-PERSISTENCE

- `docker compose up` brings Postgres + Qdrant + Ollama to healthy.
- `alembic upgrade head` applies baseline migration; `alembic_version` table contains `0001`.
- `GET /health` returns 200 with all 3 components `ok`.
- Unit tests + integration tests pass.
- `ruff check .` and `mypy src/` produce no errors.
- Commit tagged `cap-01-infra-persistence`.

## What the next plan (02) will build on top

`CAP-INFRA-TENANT-ISOLATION` (plan #2) adds:
- `users` and `tenants` ORM models + migration 0002.
- `TenantScopingMiddleware` that extracts `tenant_id` from a (yet to be added) JWT and populates the `RequestContext`.
- Tenant-aware methods on `BaseRepository` (`add`, `get`, `list`, `delete`).
- `TenantScopeViolation` error in `domain/errors/common.py`.
- Test of mutation: tenant_B endpoint cannot read tenant_A data.

Plan #2 will be written after this one is merged.
