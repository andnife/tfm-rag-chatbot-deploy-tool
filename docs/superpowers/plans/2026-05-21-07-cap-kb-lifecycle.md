# CAP-KB-LIFECYCLE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** CRUD over `KnowledgeBase` (KB) + polymorphic `Source` (`document` | `database`) ops shared by both subtypes: `ListSources`, `DetachSource`, `TestSourceConnection`. KB creation also ensures a Qdrant collection exists for the `(tenant, dim)` pair so plan #8 can ingest documents on day one. After this plan an admin can create/list/patch/delete KBs through `/api/knowledge-bases/*`; sources themselves are still empty (attach + ingest land in #8/#9).

**Architecture:**
- `KnowledgeBase` and `Source` are domain entities; `ChunkingConfig` and `EmbeddingSelection` are value objects stored as JSONB on `knowledge_bases`.
- `sources` is a single polymorphic table with `type` discriminator (`document` | `database`) and JSONB `payload`; subtype-specific construction belongs to plans #8/#9. This plan only ships the shared ops.
- `SourceConnectionTester` is a port + registry by `SourceType`. Plan #7 ships an empty registry; plans #8/#9 register testers. Until then `TestSourceConnection` returns `{ok: false, error_code: "TESTER_NOT_REGISTERED"}`.
- `DeleteKnowledgeBase` deletes the KB outright; the "blocked if a chatbot references the KB" rule is enforced at the DB layer with `ON DELETE RESTRICT` on `chatbot_knowledge_base.kb_id`, introduced by plan #10. This plan defines `KnowledgeBaseInUseError` so plan #10 can raise it without churn, but the check is currently a no-op (no chatbots table yet).
- Repositories are tenant-scoped via `BaseRepository` (plan #2). `SourceRepository` scopes through its parent KB (the use case loads the tenant-scoped KB first, then queries sources by `kb_id`).

**Tech Stack:** No new deps beyond plans 1-6.

**Depends on:** plan #1 (engine, settings), plan #2 (TenantScopingMiddleware, BaseRepository), plan #5 (BootstrapTenant — needed to seed a tenant in integration tests), plan #6 (embedding catalog).

**Out of scope (deferred):**
- `AttachDocumentSource`, `AttachDatabaseSource`, `IngestSource`, `ReindexSource` → plans #8/#9.
- Real source-connection testers (cloud-storage, SQL drivers) → plans #8/#9 register adapters into the registry shipped here.
- Chatbot referencing on `DeleteKnowledgeBase` → plan #10 (adds `chatbot_knowledge_base` table + RESTRICT FK).
- `UpdateKnowledgeBase` with embedding/chunking change triggering reindex → plan #8 wires the reindex side-effect; this plan returns a `reindex_required` flag in the response so the UI can warn.

---

## File structure

```
backend/src/tfm_rag/
├── domain/
│   ├── value_objects/
│   │   ├── __init__.py
│   │   ├── chunking_config.py
│   │   └── embedding_selection.py
│   ├── entities/
│   │   ├── knowledge_base.py
│   │   └── source.py
│   ├── errors/
│   │   └── knowledge.py
│   └── ports/
│       └── source_connection_tester.py
├── infrastructure/
│   └── persistence/
│       ├── models/
│       │   ├── knowledge_bases.py
│       │   └── sources.py
│       └── repositories/
│           ├── knowledge_bases_repo.py
│           └── sources_repo.py
└── application/
    └── knowledge/
        ├── __init__.py
        ├── create_knowledge_base.py
        ├── update_knowledge_base.py
        ├── list_knowledge_bases.py
        ├── get_knowledge_base.py
        ├── delete_knowledge_base.py
        ├── list_sources.py
        ├── detach_source.py
        └── test_source_connection.py

backend/alembic/versions/
└── 0004_knowledge_bases_and_sources.py

backend/src/tfm_rag/infrastructure/api/routers/
└── knowledge_bases.py

backend/tests/unit/
├── test_chunking_config.py
├── test_embedding_selection.py
└── test_knowledge_use_cases.py

backend/tests/integration/
└── test_knowledge_endpoints.py
```

---

## Task 1 — Domain: value objects, entities, errors, port

### Step 1.1: Create `backend/src/tfm_rag/domain/value_objects/__init__.py` (empty)

### Step 1.2: Create `backend/src/tfm_rag/domain/value_objects/chunking_config.py`

```python
from dataclasses import dataclass
from typing import Any, Literal

from tfm_rag.domain.errors.common import ValidationError

ChunkingStrategy = Literal["recursive", "by_paragraph", "fixed"]

CHUNK_SIZE_MIN = 100
CHUNK_SIZE_MAX = 4000
CHUNK_OVERLAP_MIN = 0
CHUNK_OVERLAP_MAX = 500


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    strategy: ChunkingStrategy
    chunk_size: int
    chunk_overlap: int

    def __post_init__(self) -> None:
        if not (CHUNK_SIZE_MIN <= self.chunk_size <= CHUNK_SIZE_MAX):
            raise ValidationError(
                f"chunk_size must be in [{CHUNK_SIZE_MIN},{CHUNK_SIZE_MAX}], "
                f"got {self.chunk_size}"
            )
        if not (CHUNK_OVERLAP_MIN <= self.chunk_overlap <= CHUNK_OVERLAP_MAX):
            raise ValidationError(
                f"chunk_overlap must be in [{CHUNK_OVERLAP_MIN},{CHUNK_OVERLAP_MAX}], "
                f"got {self.chunk_overlap}"
            )
        if self.chunk_overlap >= self.chunk_size:
            raise ValidationError(
                f"chunk_overlap ({self.chunk_overlap}) must be < "
                f"chunk_size ({self.chunk_size})"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChunkingConfig":
        return cls(
            strategy=data["strategy"],
            chunk_size=int(data["chunk_size"]),
            chunk_overlap=int(data["chunk_overlap"]),
        )

    @classmethod
    def default(cls) -> "ChunkingConfig":
        return cls(strategy="recursive", chunk_size=1000, chunk_overlap=200)
```

### Step 1.3: Create `backend/src/tfm_rag/domain/value_objects/embedding_selection.py`

```python
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from tfm_rag.domain.catalog.embedding_providers import EMBEDDING_PROVIDER_CATALOG
from tfm_rag.domain.errors.common import ValidationError


@dataclass(frozen=True, slots=True)
class EmbeddingSelection:
    """Frozen pointer to a (provider, model, dim) tuple + the credential to use.

    `credential_id` is the ProviderCredential row id (plan #6). For SERVER_ENV
    providers (Ollama) this points to the tenant's `default` Ollama credential
    seeded by BootstrapTenant.
    """

    provider_id: str
    credential_id: UUID
    model_id: str
    dim: int

    def __post_init__(self) -> None:
        descriptor = EMBEDDING_PROVIDER_CATALOG.get(self.provider_id)
        if descriptor is None:
            raise ValidationError(
                f"Unknown embedding provider: {self.provider_id!r}"
            )
        known = {(m, d) for m, d in descriptor.default_models}
        if (self.model_id, self.dim) not in known:
            raise ValidationError(
                f"Model ({self.model_id!r}, dim={self.dim}) is not in the "
                f"catalog for provider {self.provider_id!r}. "
                f"Known: {sorted(known)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "credential_id": str(self.credential_id),
            "model_id": self.model_id,
            "dim": self.dim,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EmbeddingSelection":
        return cls(
            provider_id=data["provider_id"],
            credential_id=UUID(str(data["credential_id"])),
            model_id=data["model_id"],
            dim=int(data["dim"]),
        )
```

### Step 1.4: Create `backend/src/tfm_rag/domain/entities/knowledge_base.py`

```python
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection


@dataclass(frozen=True, slots=True)
class KnowledgeBase:
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    chunking_config: ChunkingConfig
    embedding_selection: EmbeddingSelection
    created_at: datetime
    updated_at: datetime
```

### Step 1.5: Create `backend/src/tfm_rag/domain/entities/source.py`

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

SourceType = Literal["document", "database"]
IngestStatus = Literal["not_started", "queued", "running", "done", "failed"]


@dataclass(frozen=True, slots=True)
class Source:
    """Polymorphic source row. `type` selects the schema of `payload`.

    payload (document):
        kind: 'upload' | 'cloud'
        storage_uri | cloud_folder_ref
        filename, mime_type, size_bytes, cloud_provider?
    payload (database):
        driver: 'postgres' | 'mysql'
        credential_id, host, port, db_name, ssl_mode, schema_snapshot?
    """

    id: UUID
    kb_id: UUID
    type: SourceType
    payload: dict[str, Any]
    ingest_status: IngestStatus
    last_ingest_at: datetime | None
    error: str | None
```

### Step 1.6: Create `backend/src/tfm_rag/domain/errors/knowledge.py`

```python
from tfm_rag.domain.errors.common import DomainError, NotFoundError


class KnowledgeBaseNotFoundError(NotFoundError):
    """Raised when a KB does not exist in the tenant."""


class KnowledgeBaseInUseError(DomainError):
    """Raised when a KB cannot be deleted because a chatbot references it.

    Defined in plan #7 so the error class is stable. The actual check fires
    in plan #10 once chatbots + chatbot_knowledge_base exist.
    """


class IncompatibleEmbeddingsError(DomainError):
    """Raised when KBs attached to the same chatbot disagree on embedding.

    Defined here so plan #10 can raise it. Plan #7 doesn't trigger it.
    """


class SourceNotFoundError(NotFoundError):
    """Raised when a Source does not exist in the KB."""


class UnsupportedSourceTypeError(DomainError):
    """Raised when a tester / handler is requested for an unknown SourceType."""
```

### Step 1.7: Create `backend/src/tfm_rag/domain/ports/source_connection_tester.py`

```python
from dataclasses import dataclass
from typing import Any, Protocol

from tfm_rag.domain.entities.source import SourceType


@dataclass(frozen=True, slots=True)
class SourceConnectionTestResult:
    ok: bool
    error: str | None
    details: dict[str, Any] | None = None


class SourceConnectionTester(Protocol):
    """Pre-attach tester for one SourceType. Implementations live in adapters.

    The `spec` dict has the same shape that `payload` will have once the
    Source is persisted, but the tester MUST NOT persist anything.
    """

    async def test(self, spec: dict[str, Any]) -> SourceConnectionTestResult: ...


# Registry populated by adapters at import time. Plans #8/#9 will register
# their testers here. Plan #7 leaves it empty on purpose.
SOURCE_CONNECTION_TESTERS: dict[SourceType, SourceConnectionTester] = {}
```

- [ ] **Step 1.8: Write the failing tests for value objects**

Create `backend/tests/unit/test_chunking_config.py`:

```python
import pytest

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig


def test_default_is_valid() -> None:
    c = ChunkingConfig.default()
    assert c.strategy == "recursive"
    assert c.chunk_size == 1000
    assert c.chunk_overlap == 200


def test_round_trip() -> None:
    c = ChunkingConfig(strategy="fixed", chunk_size=512, chunk_overlap=64)
    assert ChunkingConfig.from_dict(c.to_dict()) == c


def test_chunk_size_below_min_rejected() -> None:
    with pytest.raises(ValidationError):
        ChunkingConfig(strategy="recursive", chunk_size=10, chunk_overlap=0)


def test_chunk_size_above_max_rejected() -> None:
    with pytest.raises(ValidationError):
        ChunkingConfig(strategy="recursive", chunk_size=10_000, chunk_overlap=0)


def test_overlap_greater_than_size_rejected() -> None:
    with pytest.raises(ValidationError):
        ChunkingConfig(strategy="recursive", chunk_size=500, chunk_overlap=600)


def test_overlap_equal_to_size_rejected() -> None:
    with pytest.raises(ValidationError):
        ChunkingConfig(strategy="recursive", chunk_size=500, chunk_overlap=500)
```

Create `backend/tests/unit/test_embedding_selection.py`:

```python
import pytest
from uuid import uuid4

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection


def test_known_combo_accepted() -> None:
    s = EmbeddingSelection(
        provider_id="ollama",
        credential_id=uuid4(),
        model_id="bge-m3",
        dim=1024,
    )
    assert s.dim == 1024


def test_unknown_provider_rejected() -> None:
    with pytest.raises(ValidationError, match="Unknown embedding provider"):
        EmbeddingSelection(
            provider_id="not_a_provider",
            credential_id=uuid4(),
            model_id="x",
            dim=1024,
        )


def test_unknown_model_rejected() -> None:
    with pytest.raises(ValidationError, match="not in the catalog"):
        EmbeddingSelection(
            provider_id="ollama",
            credential_id=uuid4(),
            model_id="bge-m3",
            dim=999,
        )


def test_round_trip() -> None:
    cid = uuid4()
    s = EmbeddingSelection(
        provider_id="ollama",
        credential_id=cid,
        model_id="bge-m3",
        dim=1024,
    )
    assert EmbeddingSelection.from_dict(s.to_dict()) == s
```

- [ ] **Step 1.9: Run tests, confirm they fail with `ModuleNotFoundError`**

Run: `pytest tests/unit/test_chunking_config.py tests/unit/test_embedding_selection.py -v`
Expected: errors before collection because the modules don't exist yet.

- [ ] **Step 1.10: Create the files from steps 1.1–1.7**

Now create the actual files. Re-run the same command. Expected: all 9 tests PASS.

- [ ] **Step 1.11: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/domain/value_objects backend/src/tfm_rag/domain/entities/knowledge_base.py backend/src/tfm_rag/domain/entities/source.py backend/src/tfm_rag/domain/errors/knowledge.py backend/src/tfm_rag/domain/ports/source_connection_tester.py backend/tests/unit/test_chunking_config.py backend/tests/unit/test_embedding_selection.py
git commit -m "feat(domain): KnowledgeBase + Source entities, VOs, errors, tester port"
```

---

## Task 2 — Persistence: ORM models + migration 0004

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/persistence/models/knowledge_bases.py`
- Create: `backend/src/tfm_rag/infrastructure/persistence/models/sources.py`
- Create: `backend/alembic/versions/0004_knowledge_bases_and_sources.py`
- Modify: `backend/alembic/env.py` (register new model modules)

- [ ] **Step 2.1: Write the failing integration test for migration 0004**

Create `backend/tests/integration/test_knowledge_migration.py`:

```python
import asyncio
import subprocess

import pytest
from sqlalchemy import inspect

from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings


@pytest.mark.integration
async def test_migration_0004_creates_kb_and_sources(settings: Settings) -> None:
    result = await asyncio.to_thread(
        subprocess.run,
        ["alembic", "upgrade", "head"],
        cwd=".",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    engine = build_engine(settings.postgres_url)
    build_session_factory(engine)
    async with engine.connect() as conn:
        tables = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_table_names()
        )
        assert "knowledge_bases" in tables
        assert "sources" in tables
        kb_cols = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("knowledge_bases")}
        )
        assert {"id", "tenant_id", "name", "description",
                "chunking_config", "embedding_selection",
                "created_at", "updated_at"} <= kb_cols
        src_cols = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("sources")}
        )
        assert {"id", "kb_id", "type", "payload",
                "ingest_status", "last_ingest_at", "error"} <= src_cols
    await engine.dispose()
```

- [ ] **Step 2.2: Create `backend/src/tfm_rag/infrastructure/persistence/models/knowledge_bases.py`**

```python
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from tfm_rag.infrastructure.persistence.base import Base


class KnowledgeBaseRow(Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "name",
            name="uq_knowledge_bases_tenant_name",
        ),
        CheckConstraint(
            "(embedding_selection ? 'dim') AND (embedding_selection ? 'model_id')",
            name="ck_knowledge_bases_embedding_keys",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        # FK declared in migration; column is also defined here for ORM use.
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    chunking_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    embedding_selection: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
```

- [ ] **Step 2.3: Create `backend/src/tfm_rag/infrastructure/persistence/models/sources.py`**

```python
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from tfm_rag.infrastructure.persistence.base import Base


class SourceRow(Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint(
            "type IN ('document','database')",
            name="ck_sources_type",
        ),
        CheckConstraint(
            "ingest_status IN ('not_started','queued','running','done','failed')",
            name="ck_sources_ingest_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    kb_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ingest_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="not_started"
    )
    last_ingest_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
```

- [ ] **Step 2.4: Create `backend/alembic/versions/0004_knowledge_bases_and_sources.py`**

```python
"""create knowledge_bases and sources tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-21 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("chunking_config", postgresql.JSONB(), nullable=False),
        sa.Column("embedding_selection", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "name",
            name="uq_knowledge_bases_tenant_name",
        ),
        sa.CheckConstraint(
            "(embedding_selection ? 'dim') AND (embedding_selection ? 'model_id')",
            name="ck_knowledge_bases_embedding_keys",
        ),
    )
    op.create_index(
        "ix_knowledge_bases_tenant_id", "knowledge_bases", ["tenant_id"]
    )

    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "kb_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "ingest_status",
            sa.String(length=16),
            nullable=False,
            server_default="not_started",
        ),
        sa.Column("last_ingest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.CheckConstraint(
            "type IN ('document','database')",
            name="ck_sources_type",
        ),
        sa.CheckConstraint(
            "ingest_status IN ('not_started','queued','running','done','failed')",
            name="ck_sources_ingest_status",
        ),
    )
    op.create_index("ix_sources_kb_id", "sources", ["kb_id"])
    op.create_index("ix_sources_kb_id_type", "sources", ["kb_id", "type"])


def downgrade() -> None:
    op.drop_index("ix_sources_kb_id_type", table_name="sources")
    op.drop_index("ix_sources_kb_id", table_name="sources")
    op.drop_table("sources")
    op.drop_index("ix_knowledge_bases_tenant_id", table_name="knowledge_bases")
    op.drop_table("knowledge_bases")
```

- [ ] **Step 2.5: Register the new model modules in `backend/alembic/env.py`**

Edit `backend/alembic/env.py` to import the new modules alongside the existing imports:

```python
# Import all ORM model modules so Base.metadata sees them for autogenerate
from tfm_rag.infrastructure.persistence.models import (
    knowledge_bases,  # noqa: F401
    provider_credentials,  # noqa: F401
    sources,  # noqa: F401
    tenants,  # noqa: F401
    users,  # noqa: F401
)
```

- [ ] **Step 2.6: Reset DB and run the migration test**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
docker exec tfm-rag-postgres-1 psql -U tfm -d tfm_rag \
  -c "DROP TABLE IF EXISTS sources, knowledge_bases, provider_credentials, users, tenants, alembic_version CASCADE;"
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
pytest tests/integration/test_knowledge_migration.py -m integration -v
```

Expected: PASS — tables `knowledge_bases` and `sources` present with the right columns.

- [ ] **Step 2.7: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/infrastructure/persistence/models/knowledge_bases.py backend/src/tfm_rag/infrastructure/persistence/models/sources.py backend/alembic/versions/0004_knowledge_bases_and_sources.py backend/alembic/env.py backend/tests/integration/test_knowledge_migration.py
git commit -m "feat(infra): knowledge_bases + sources ORM + migration 0004"
```

---

## Task 3 — Repositories

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/persistence/repositories/knowledge_bases_repo.py`
- Create: `backend/src/tfm_rag/infrastructure/persistence/repositories/sources_repo.py`

- [ ] **Step 3.1: Create `backend/src/tfm_rag/infrastructure/persistence/repositories/knowledge_bases_repo.py`**

```python
from sqlalchemy import select

from tfm_rag.infrastructure.persistence.models.knowledge_bases import (
    KnowledgeBaseRow,
)
from tfm_rag.infrastructure.persistence.repository import BaseRepository


class KnowledgeBaseRepository(BaseRepository[KnowledgeBaseRow]):
    model = KnowledgeBaseRow

    async def find_by_name(self, name: str) -> KnowledgeBaseRow | None:
        stmt = select(KnowledgeBaseRow).where(
            KnowledgeBaseRow.tenant_id == self._ctx.tenant_id,
            KnowledgeBaseRow.name == name,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()
```

- [ ] **Step 3.2: Create `backend/src/tfm_rag/infrastructure/persistence/repositories/sources_repo.py`**

```python
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from tfm_rag.domain.errors.knowledge import SourceNotFoundError
from tfm_rag.infrastructure.persistence.models.sources import SourceRow


class SourceRepository:
    """Sources are scoped through their parent KB (which is tenant-scoped).

    The use case is responsible for loading the KB first (which enforces
    tenant scope); this repo only operates within an already-validated kb_id.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_kb(self, kb_id: UUID) -> list[SourceRow]:
        stmt = select(SourceRow).where(SourceRow.kb_id == kb_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def get(self, kb_id: UUID, source_id: UUID) -> SourceRow:
        stmt = select(SourceRow).where(
            SourceRow.id == source_id,
            SourceRow.kb_id == kb_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise SourceNotFoundError(
                f"Source({source_id}) not found in KB({kb_id})"
            )
        return row

    async def delete(self, kb_id: UUID, source_id: UUID) -> None:
        stmt = delete(SourceRow).where(
            SourceRow.id == source_id,
            SourceRow.kb_id == kb_id,
        )
        result: CursorResult[Any] = await self._session.execute(stmt)  # type: ignore[assignment]
        if result.rowcount == 0:
            raise SourceNotFoundError(
                f"Source({source_id}) not found in KB({kb_id})"
            )
```

- [ ] **Step 3.3: Run ruff + mypy to confirm types**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
ruff check .
mypy src/
```

Expected: both clean.

- [ ] **Step 3.4: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/infrastructure/persistence/repositories/knowledge_bases_repo.py backend/src/tfm_rag/infrastructure/persistence/repositories/sources_repo.py
git commit -m "feat(infra): KnowledgeBaseRepository + SourceRepository"
```

---

## Task 4 — Application use cases

**Files (each step creates one file):**
- `backend/src/tfm_rag/application/knowledge/__init__.py` (empty)
- `backend/src/tfm_rag/application/knowledge/create_knowledge_base.py`
- `backend/src/tfm_rag/application/knowledge/update_knowledge_base.py`
- `backend/src/tfm_rag/application/knowledge/list_knowledge_bases.py`
- `backend/src/tfm_rag/application/knowledge/get_knowledge_base.py`
- `backend/src/tfm_rag/application/knowledge/delete_knowledge_base.py`
- `backend/src/tfm_rag/application/knowledge/list_sources.py`
- `backend/src/tfm_rag/application/knowledge/detach_source.py`
- `backend/src/tfm_rag/application/knowledge/test_source_connection.py`
- `backend/tests/unit/test_knowledge_use_cases.py`

- [ ] **Step 4.1: Write the failing unit tests**

Create `backend/tests/unit/test_knowledge_use_cases.py`:

```python
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from tfm_rag.application.knowledge.create_knowledge_base import (
    create_knowledge_base,
)
from tfm_rag.application.knowledge.delete_knowledge_base import (
    delete_knowledge_base,
)
from tfm_rag.application.knowledge.detach_source import detach_source
from tfm_rag.application.knowledge.list_knowledge_bases import (
    list_knowledge_bases,
)
from tfm_rag.application.knowledge.list_sources import list_sources
from tfm_rag.application.knowledge.test_source_connection import (
    test_source_connection,
)
from tfm_rag.application.knowledge.update_knowledge_base import (
    update_knowledge_base,
)
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.errors.knowledge import (
    KnowledgeBaseNotFoundError,
    SourceNotFoundError,
)
from tfm_rag.domain.ports.source_connection_tester import (
    SOURCE_CONNECTION_TESTERS,
    SourceConnectionTestResult,
)
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.infrastructure.persistence.repository import RequestContext


def _ctx() -> RequestContext:
    return RequestContext(tenant_id=uuid4(), user_id=uuid4())


def _selection(credential_id: UUID | None = None) -> EmbeddingSelection:
    return EmbeddingSelection(
        provider_id="ollama",
        credential_id=credential_id or uuid4(),
        model_id="bge-m3",
        dim=1024,
    )


@pytest.mark.asyncio
async def test_create_knowledge_base_ensures_qdrant_and_persists() -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    ctx = _ctx()
    qdrant = MagicMock()
    qdrant.ensure_collection = AsyncMock(return_value="kb_chunks__t__1024")
    repo = MagicMock()
    repo.find_by_name = AsyncMock(return_value=None)
    repo.add = AsyncMock(side_effect=lambda r: r)
    selection = _selection()

    result = await create_knowledge_base(
        session,
        ctx,
        qdrant,
        repo_factory=lambda s, c: repo,
        name="docs",
        description="manuals",
        chunking_config=ChunkingConfig.default(),
        embedding_selection=selection,
    )

    qdrant.ensure_collection.assert_awaited_once_with(ctx.tenant_id, 1024)
    repo.add.assert_awaited_once()
    assert result.name == "docs"
    assert result.embedding_selection.dim == 1024


@pytest.mark.asyncio
async def test_create_knowledge_base_rejects_duplicate_name() -> None:
    session = MagicMock()
    ctx = _ctx()
    qdrant = MagicMock()
    qdrant.ensure_collection = AsyncMock()
    repo = MagicMock()
    existing = MagicMock(name="row")
    repo.find_by_name = AsyncMock(return_value=existing)

    with pytest.raises(ValidationError, match="already exists"):
        await create_knowledge_base(
            session,
            ctx,
            qdrant,
            repo_factory=lambda s, c: repo,
            name="docs",
            description=None,
            chunking_config=ChunkingConfig.default(),
            embedding_selection=_selection(),
        )

    qdrant.ensure_collection.assert_not_called()


@pytest.mark.asyncio
async def test_update_knowledge_base_flags_reindex_when_embedding_changes() -> None:
    session = MagicMock()
    session.flush = AsyncMock()
    ctx = _ctx()
    old_selection = _selection()
    new_selection = EmbeddingSelection(
        provider_id="ollama",
        credential_id=old_selection.credential_id,
        model_id="nomic-embed-text",
        dim=768,
    )
    existing = MagicMock()
    existing.embedding_selection = old_selection.to_dict()
    existing.chunking_config = ChunkingConfig.default().to_dict()
    existing.id = uuid4()
    existing.tenant_id = ctx.tenant_id
    existing.name = "docs"
    existing.description = None
    existing.created_at = None
    existing.updated_at = None
    repo = MagicMock()
    repo.get = AsyncMock(return_value=existing)
    qdrant = MagicMock()
    qdrant.ensure_collection = AsyncMock(return_value="kb_chunks__t__768")

    result = await update_knowledge_base(
        session,
        ctx,
        qdrant,
        repo_factory=lambda s, c: repo,
        kb_id=existing.id,
        name=None,
        description=None,
        chunking_config=None,
        embedding_selection=new_selection,
    )

    assert result.reindex_required is True
    qdrant.ensure_collection.assert_awaited_once_with(ctx.tenant_id, 768)


@pytest.mark.asyncio
async def test_update_knowledge_base_no_reindex_when_only_name_changes() -> None:
    session = MagicMock()
    session.flush = AsyncMock()
    ctx = _ctx()
    selection = _selection()
    existing = MagicMock()
    existing.embedding_selection = selection.to_dict()
    existing.chunking_config = ChunkingConfig.default().to_dict()
    existing.id = uuid4()
    existing.tenant_id = ctx.tenant_id
    existing.name = "old"
    existing.description = None
    existing.created_at = None
    existing.updated_at = None
    repo = MagicMock()
    repo.get = AsyncMock(return_value=existing)
    qdrant = MagicMock()

    result = await update_knowledge_base(
        session,
        ctx,
        qdrant,
        repo_factory=lambda s, c: repo,
        kb_id=existing.id,
        name="new",
        description=None,
        chunking_config=None,
        embedding_selection=None,
    )

    assert result.reindex_required is False
    qdrant.ensure_collection.assert_not_called()
    assert existing.name == "new"


@pytest.mark.asyncio
async def test_list_knowledge_bases_uses_pagination() -> None:
    session = MagicMock()
    ctx = _ctx()
    repo = MagicMock()
    repo.list = AsyncMock(return_value=[])

    await list_knowledge_bases(
        session, ctx, repo_factory=lambda s, c: repo, limit=5, offset=10
    )

    repo.list.assert_awaited_once_with(limit=5, offset=10)


@pytest.mark.asyncio
async def test_delete_knowledge_base_calls_repo() -> None:
    session = MagicMock()
    ctx = _ctx()
    repo = MagicMock()
    repo.delete = AsyncMock()
    kb_id = uuid4()

    await delete_knowledge_base(
        session, ctx, repo_factory=lambda s, c: repo, kb_id=kb_id
    )

    repo.delete.assert_awaited_once_with(kb_id)


@pytest.mark.asyncio
async def test_list_sources_loads_kb_then_lists() -> None:
    session = MagicMock()
    ctx = _ctx()
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.id = uuid4()
    kb_repo.get = AsyncMock(return_value=kb_row)
    src_repo = MagicMock()
    src_repo.list_by_kb = AsyncMock(return_value=[])

    result = await list_sources(
        session, ctx,
        kb_repo_factory=lambda s, c: kb_repo,
        sources_repo_factory=lambda s: src_repo,
        kb_id=kb_row.id,
    )

    kb_repo.get.assert_awaited_once_with(kb_row.id)
    src_repo.list_by_kb.assert_awaited_once_with(kb_row.id)
    assert result == []


@pytest.mark.asyncio
async def test_list_sources_raises_when_kb_missing() -> None:
    from tfm_rag.domain.errors.common import NotFoundError

    session = MagicMock()
    ctx = _ctx()
    kb_repo = MagicMock()
    kb_repo.get = AsyncMock(side_effect=NotFoundError("nope"))
    src_repo = MagicMock()
    kb_id = uuid4()

    with pytest.raises(KnowledgeBaseNotFoundError):
        await list_sources(
            session, ctx,
            kb_repo_factory=lambda s, c: kb_repo,
            sources_repo_factory=lambda s: src_repo,
            kb_id=kb_id,
        )


@pytest.mark.asyncio
async def test_detach_source_validates_kb_and_deletes() -> None:
    session = MagicMock()
    ctx = _ctx()
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.id = uuid4()
    kb_repo.get = AsyncMock(return_value=kb_row)
    src_repo = MagicMock()
    src_repo.delete = AsyncMock()
    source_id = uuid4()

    await detach_source(
        session, ctx,
        kb_repo_factory=lambda s, c: kb_repo,
        sources_repo_factory=lambda s: src_repo,
        kb_id=kb_row.id,
        source_id=source_id,
    )

    src_repo.delete.assert_awaited_once_with(kb_row.id, source_id)


@pytest.mark.asyncio
async def test_detach_source_raises_when_source_missing() -> None:
    session = MagicMock()
    ctx = _ctx()
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.id = uuid4()
    kb_repo.get = AsyncMock(return_value=kb_row)
    src_repo = MagicMock()
    src_repo.delete = AsyncMock(side_effect=SourceNotFoundError("nope"))

    with pytest.raises(SourceNotFoundError):
        await detach_source(
            session, ctx,
            kb_repo_factory=lambda s, c: kb_repo,
            sources_repo_factory=lambda s: src_repo,
            kb_id=kb_row.id,
            source_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_test_source_connection_returns_not_registered_when_no_tester() -> None:
    SOURCE_CONNECTION_TESTERS.clear()

    result = await test_source_connection(
        spec_type="document",
        spec={"kind": "cloud", "cloud_folder_ref": "x"},
    )

    assert result.ok is False
    assert result.error is not None
    assert "TESTER_NOT_REGISTERED" in result.error


@pytest.mark.asyncio
async def test_test_source_connection_invokes_registered_tester() -> None:
    captured: dict[str, Any] = {}

    class FakeTester:
        async def test(self, spec: dict[str, Any]) -> SourceConnectionTestResult:
            captured["spec"] = spec
            return SourceConnectionTestResult(ok=True, error=None)

    SOURCE_CONNECTION_TESTERS["database"] = FakeTester()
    try:
        result = await test_source_connection(
            spec_type="database",
            spec={"driver": "postgres", "host": "x"},
        )
    finally:
        del SOURCE_CONNECTION_TESTERS["database"]

    assert result.ok is True
    assert captured["spec"]["driver"] == "postgres"
```

- [ ] **Step 4.2: Run the tests, confirm they fail with `ModuleNotFoundError`**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
pytest tests/unit/test_knowledge_use_cases.py -v
```

Expected: collection errors because the application modules don't exist.

- [ ] **Step 4.3: Create `backend/src/tfm_rag/application/knowledge/__init__.py` (empty)**

- [ ] **Step 4.4: Create `backend/src/tfm_rag/application/knowledge/create_knowledge_base.py`**

```python
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.entities.knowledge_base import KnowledgeBase
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.infrastructure.persistence.models.knowledge_bases import (
    KnowledgeBaseRow,
)
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore

KbRepoFactory = Callable[
    [AsyncSession, RequestContext], KnowledgeBaseRepository
]


def _default_repo(
    session: AsyncSession, ctx: RequestContext
) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session, ctx)


@dataclass(frozen=True, slots=True)
class KnowledgeBaseView:
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    chunking_config: ChunkingConfig
    embedding_selection: EmbeddingSelection


def _to_view(row: KnowledgeBaseRow) -> KnowledgeBaseView:
    return KnowledgeBaseView(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        description=row.description,
        chunking_config=ChunkingConfig.from_dict(row.chunking_config),
        embedding_selection=EmbeddingSelection.from_dict(row.embedding_selection),
    )


async def create_knowledge_base(
    session: AsyncSession,
    ctx: RequestContext,
    qdrant: QdrantStore,
    *,
    repo_factory: KbRepoFactory = _default_repo,
    name: str,
    description: str | None,
    chunking_config: ChunkingConfig,
    embedding_selection: EmbeddingSelection,
) -> KnowledgeBaseView:
    name = name.strip()
    if not name:
        raise ValidationError("name must not be empty")
    repo = repo_factory(session, ctx)
    if await repo.find_by_name(name) is not None:
        raise ValidationError(f"KnowledgeBase named {name!r} already exists in tenant")

    # Provision the Qdrant collection for the chosen embedding dim before
    # persisting the KB row, so downstream ingestion (plan #8) can rely on it.
    await qdrant.ensure_collection(ctx.tenant_id, embedding_selection.dim)

    row = KnowledgeBaseRow(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        name=name,
        description=description,
        chunking_config=chunking_config.to_dict(),
        embedding_selection=embedding_selection.to_dict(),
    )
    await repo.add(row)
    return _to_view(row)
```

- [ ] **Step 4.5: Create `backend/src/tfm_rag/application/knowledge/update_knowledge_base.py`**

```python
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.knowledge.create_knowledge_base import (
    KnowledgeBaseView,
    _to_view,
)
from tfm_rag.domain.errors.common import NotFoundError, ValidationError
from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore

KbRepoFactory = Callable[
    [AsyncSession, RequestContext], KnowledgeBaseRepository
]


def _default_repo(
    session: AsyncSession, ctx: RequestContext
) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session, ctx)


@dataclass(frozen=True, slots=True)
class UpdateKnowledgeBaseResult:
    kb: KnowledgeBaseView
    reindex_required: bool


async def update_knowledge_base(
    session: AsyncSession,
    ctx: RequestContext,
    qdrant: QdrantStore,
    *,
    repo_factory: KbRepoFactory = _default_repo,
    kb_id: UUID,
    name: str | None,
    description: str | None,
    chunking_config: ChunkingConfig | None,
    embedding_selection: EmbeddingSelection | None,
) -> UpdateKnowledgeBaseResult:
    repo = repo_factory(session, ctx)
    try:
        row = await repo.get(kb_id)
    except NotFoundError as exc:
        raise KnowledgeBaseNotFoundError(str(exc)) from exc

    reindex = False

    if name is not None:
        name = name.strip()
        if not name:
            raise ValidationError("name must not be empty")
        row.name = name
    if description is not None:
        row.description = description or None

    if chunking_config is not None:
        old = ChunkingConfig.from_dict(row.chunking_config)
        if chunking_config != old:
            row.chunking_config = chunking_config.to_dict()
            reindex = True

    if embedding_selection is not None:
        old_sel = EmbeddingSelection.from_dict(row.embedding_selection)
        if embedding_selection != old_sel:
            row.embedding_selection = embedding_selection.to_dict()
            if embedding_selection.dim != old_sel.dim:
                # Provision the new (tenant, dim) collection so plan #8 can
                # reindex into it.
                await qdrant.ensure_collection(
                    ctx.tenant_id, embedding_selection.dim
                )
            reindex = True

    await session.flush()
    return UpdateKnowledgeBaseResult(kb=_to_view(row), reindex_required=reindex)
```

- [ ] **Step 4.6: Create `backend/src/tfm_rag/application/knowledge/list_knowledge_bases.py`**

```python
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.knowledge.create_knowledge_base import (
    KnowledgeBaseView,
    _to_view,
)
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

KbRepoFactory = Callable[
    [AsyncSession, RequestContext], KnowledgeBaseRepository
]


def _default_repo(
    session: AsyncSession, ctx: RequestContext
) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session, ctx)


async def list_knowledge_bases(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    repo_factory: KbRepoFactory = _default_repo,
    limit: int = 20,
    offset: int = 0,
) -> list[KnowledgeBaseView]:
    repo = repo_factory(session, ctx)
    rows = await repo.list(limit=limit, offset=offset)
    return [_to_view(r) for r in rows]
```

- [ ] **Step 4.7: Create `backend/src/tfm_rag/application/knowledge/get_knowledge_base.py`**

```python
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.knowledge.create_knowledge_base import (
    KnowledgeBaseView,
    _to_view,
)
from tfm_rag.domain.entities.source import IngestStatus, SourceType
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError
from tfm_rag.infrastructure.persistence.models.sources import SourceRow
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repositories.sources_repo import (
    SourceRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

KbRepoFactory = Callable[
    [AsyncSession, RequestContext], KnowledgeBaseRepository
]
SrcRepoFactory = Callable[[AsyncSession], SourceRepository]


def _default_kb_repo(
    session: AsyncSession, ctx: RequestContext
) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session, ctx)


def _default_src_repo(session: AsyncSession) -> SourceRepository:
    return SourceRepository(session)


@dataclass(frozen=True, slots=True)
class SourceView:
    id: UUID
    kb_id: UUID
    type: SourceType
    ingest_status: IngestStatus


def _src_view(row: SourceRow) -> SourceView:
    return SourceView(
        id=row.id,
        kb_id=row.kb_id,
        type=row.type,  # type: ignore[arg-type]
        ingest_status=row.ingest_status,  # type: ignore[arg-type]
    )


@dataclass(frozen=True, slots=True)
class KnowledgeBaseDetailView:
    kb: KnowledgeBaseView
    sources: list[SourceView]


async def get_knowledge_base(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    kb_repo_factory: KbRepoFactory = _default_kb_repo,
    sources_repo_factory: SrcRepoFactory = _default_src_repo,
    kb_id: UUID,
) -> KnowledgeBaseDetailView:
    kb_repo = kb_repo_factory(session, ctx)
    try:
        kb_row = await kb_repo.get(kb_id)
    except NotFoundError as exc:
        raise KnowledgeBaseNotFoundError(str(exc)) from exc
    src_repo = sources_repo_factory(session)
    src_rows = await src_repo.list_by_kb(kb_id)
    return KnowledgeBaseDetailView(
        kb=_to_view(kb_row),
        sources=[_src_view(r) for r in src_rows],
    )
```

- [ ] **Step 4.8: Create `backend/src/tfm_rag/application/knowledge/delete_knowledge_base.py`**

```python
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import (
    KnowledgeBaseInUseError,
    KnowledgeBaseNotFoundError,
)
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

KbRepoFactory = Callable[
    [AsyncSession, RequestContext], KnowledgeBaseRepository
]


def _default_repo(
    session: AsyncSession, ctx: RequestContext
) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session, ctx)


async def delete_knowledge_base(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    repo_factory: KbRepoFactory = _default_repo,
    kb_id: UUID,
) -> None:
    repo = repo_factory(session, ctx)
    try:
        await repo.delete(kb_id)
    except NotFoundError as exc:
        raise KnowledgeBaseNotFoundError(str(exc)) from exc
    except IntegrityError as exc:
        # Plan #10 wires the chatbot_knowledge_base RESTRICT FK; this maps
        # the DB-layer violation to the domain error so callers can render
        # the right 409 response without depending on SQLAlchemy types.
        raise KnowledgeBaseInUseError(
            f"KnowledgeBase({kb_id}) is referenced by a chatbot"
        ) from exc
```

- [ ] **Step 4.9: Create `backend/src/tfm_rag/application/knowledge/list_sources.py`**

```python
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.knowledge.get_knowledge_base import (
    SourceView,
    _src_view,
)
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repositories.sources_repo import (
    SourceRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

KbRepoFactory = Callable[
    [AsyncSession, RequestContext], KnowledgeBaseRepository
]
SrcRepoFactory = Callable[[AsyncSession], SourceRepository]


def _default_kb_repo(
    session: AsyncSession, ctx: RequestContext
) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session, ctx)


def _default_src_repo(session: AsyncSession) -> SourceRepository:
    return SourceRepository(session)


async def list_sources(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    kb_repo_factory: KbRepoFactory = _default_kb_repo,
    sources_repo_factory: SrcRepoFactory = _default_src_repo,
    kb_id: UUID,
) -> list[SourceView]:
    kb_repo = kb_repo_factory(session, ctx)
    try:
        await kb_repo.get(kb_id)
    except NotFoundError as exc:
        raise KnowledgeBaseNotFoundError(str(exc)) from exc
    src_repo = sources_repo_factory(session)
    rows = await src_repo.list_by_kb(kb_id)
    return [_src_view(r) for r in rows]
```

- [ ] **Step 4.10: Create `backend/src/tfm_rag/application/knowledge/detach_source.py`**

```python
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repositories.sources_repo import (
    SourceRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

KbRepoFactory = Callable[
    [AsyncSession, RequestContext], KnowledgeBaseRepository
]
SrcRepoFactory = Callable[[AsyncSession], SourceRepository]


def _default_kb_repo(
    session: AsyncSession, ctx: RequestContext
) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session, ctx)


def _default_src_repo(session: AsyncSession) -> SourceRepository:
    return SourceRepository(session)


async def detach_source(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    kb_repo_factory: KbRepoFactory = _default_kb_repo,
    sources_repo_factory: SrcRepoFactory = _default_src_repo,
    kb_id: UUID,
    source_id: UUID,
) -> None:
    """Remove a Source row from a KB.

    Plan #7 only deletes the row. Cleanup of Qdrant chunks and storage
    artefacts for `document` sources lives in plan #8 (full ingestion
    lifecycle). The split is intentional: detach is part of the polymorphic
    surface, but per-subtype cleanup belongs with the per-subtype use cases.
    """
    kb_repo = kb_repo_factory(session, ctx)
    try:
        await kb_repo.get(kb_id)
    except NotFoundError as exc:
        raise KnowledgeBaseNotFoundError(str(exc)) from exc
    src_repo = sources_repo_factory(session)
    await src_repo.delete(kb_id, source_id)
```

- [ ] **Step 4.11: Create `backend/src/tfm_rag/application/knowledge/test_source_connection.py`**

```python
from typing import Any

from tfm_rag.domain.entities.source import SourceType
from tfm_rag.domain.ports.source_connection_tester import (
    SOURCE_CONNECTION_TESTERS,
    SourceConnectionTestResult,
)


async def test_source_connection(
    *,
    spec_type: SourceType,
    spec: dict[str, Any],
) -> SourceConnectionTestResult:
    """Pre-attach connection test. Stateless — does NOT persist anything.

    Plan #7 ships an empty tester registry; plans #8 and #9 register the
    document and database testers respectively. Until then this returns a
    structured "tester not registered" result so the UI can render a
    meaningful error.
    """
    tester = SOURCE_CONNECTION_TESTERS.get(spec_type)
    if tester is None:
        return SourceConnectionTestResult(
            ok=False,
            error=(
                f"TESTER_NOT_REGISTERED: no connection tester is wired for "
                f"source type {spec_type!r} yet"
            ),
        )
    return await tester.test(spec)
```

- [ ] **Step 4.12: Re-run the unit tests, confirm they all pass**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
pytest tests/unit/test_knowledge_use_cases.py -v
```

Expected: all 12 tests PASS.

- [ ] **Step 4.13: ruff + mypy**

```bash
ruff check .
mypy src/
```

Expected: both clean.

- [ ] **Step 4.14: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/application/knowledge backend/tests/unit/test_knowledge_use_cases.py
git commit -m "feat(knowledge): KB + Source use cases (CRUD, list/detach, test-connection)"
```

---

## Task 5 — API: `/api/knowledge-bases/*`

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/api/routers/knowledge_bases.py`
- Modify: `backend/src/tfm_rag/infrastructure/api/app.py` (mount router)

- [ ] **Step 5.1: Create the router**

Create `backend/src/tfm_rag/infrastructure/api/routers/knowledge_bases.py`:

```python
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.knowledge.create_knowledge_base import (
    KnowledgeBaseView,
    create_knowledge_base,
)
from tfm_rag.application.knowledge.delete_knowledge_base import (
    delete_knowledge_base,
)
from tfm_rag.application.knowledge.detach_source import detach_source
from tfm_rag.application.knowledge.get_knowledge_base import get_knowledge_base
from tfm_rag.application.knowledge.list_knowledge_bases import (
    list_knowledge_bases,
)
from tfm_rag.application.knowledge.list_sources import list_sources
from tfm_rag.application.knowledge.test_source_connection import (
    test_source_connection,
)
from tfm_rag.application.knowledge.update_knowledge_base import (
    update_knowledge_base,
)
from tfm_rag.domain.entities.source import SourceType
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.errors.knowledge import (
    KnowledgeBaseInUseError,
    KnowledgeBaseNotFoundError,
    SourceNotFoundError,
)
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.infrastructure.api.dependencies import (
    get_current_context,
    get_session,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.settings import Settings, get_settings
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore

router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge"])


class ChunkingConfigIn(BaseModel):
    strategy: Literal["recursive", "by_paragraph", "fixed"] = "recursive"
    chunk_size: int = Field(default=1000, ge=100, le=4000)
    chunk_overlap: int = Field(default=200, ge=0, le=500)

    def to_vo(self) -> ChunkingConfig:
        return ChunkingConfig(
            strategy=self.strategy,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )


class EmbeddingSelectionIn(BaseModel):
    provider_id: str
    credential_id: UUID
    model_id: str
    dim: int

    def to_vo(self) -> EmbeddingSelection:
        return EmbeddingSelection(
            provider_id=self.provider_id,
            credential_id=self.credential_id,
            model_id=self.model_id,
            dim=self.dim,
        )


class CreateKbIn(BaseModel):
    name: str
    description: str | None = None
    chunking_config: ChunkingConfigIn = Field(default_factory=ChunkingConfigIn)
    embedding_selection: EmbeddingSelectionIn


class UpdateKbIn(BaseModel):
    name: str | None = None
    description: str | None = None
    chunking_config: ChunkingConfigIn | None = None
    embedding_selection: EmbeddingSelectionIn | None = None


class KbOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: str | None
    chunking_config: dict[str, Any]
    embedding_selection: dict[str, Any]

    @classmethod
    def from_view(cls, v: KnowledgeBaseView) -> "KbOut":
        return cls(
            id=str(v.id),
            tenant_id=str(v.tenant_id),
            name=v.name,
            description=v.description,
            chunking_config=v.chunking_config.to_dict(),
            embedding_selection=v.embedding_selection.to_dict(),
        )


class SourceOut(BaseModel):
    id: str
    kb_id: str
    type: SourceType
    ingest_status: str


class KbDetailOut(BaseModel):
    kb: KbOut
    sources: list[SourceOut]


class UpdateKbOut(BaseModel):
    kb: KbOut
    reindex_required: bool


class TestConnectionIn(BaseModel):
    type: SourceType
    spec: dict[str, Any]


def _qdrant(settings: Settings) -> QdrantStore:
    return QdrantStore(settings.qdrant_url, settings.qdrant_api_key)


@router.post("", status_code=201, response_model=KbOut)
async def create_(
    body: CreateKbIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> KbOut:
    qdrant = _qdrant(settings)
    try:
        view = await create_knowledge_base(
            session,
            ctx,
            qdrant,
            name=body.name,
            description=body.description,
            chunking_config=body.chunking_config.to_vo(),
            embedding_selection=body.embedding_selection.to_vo(),
        )
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        await qdrant.close()
    return KbOut.from_view(view)


@router.get("", response_model=list[KbOut])
async def list_(
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> list[KbOut]:
    views = await list_knowledge_bases(session, ctx, limit=limit, offset=offset)
    return [KbOut.from_view(v) for v in views]


@router.get("/{kb_id}", response_model=KbDetailOut)
async def get_(
    kb_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> KbDetailOut:
    try:
        detail = await get_knowledge_base(session, ctx, kb_id=kb_id)
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return KbDetailOut(
        kb=KbOut.from_view(detail.kb),
        sources=[
            SourceOut(
                id=str(s.id),
                kb_id=str(s.kb_id),
                type=s.type,
                ingest_status=s.ingest_status,
            )
            for s in detail.sources
        ],
    )


@router.patch("/{kb_id}", response_model=UpdateKbOut)
async def patch_(
    kb_id: UUID,
    body: UpdateKbIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> UpdateKbOut:
    qdrant = _qdrant(settings)
    try:
        result = await update_knowledge_base(
            session,
            ctx,
            qdrant,
            kb_id=kb_id,
            name=body.name,
            description=body.description,
            chunking_config=(
                body.chunking_config.to_vo() if body.chunking_config else None
            ),
            embedding_selection=(
                body.embedding_selection.to_vo()
                if body.embedding_selection
                else None
            ),
        )
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        await qdrant.close()
    return UpdateKbOut(
        kb=KbOut.from_view(result.kb),
        reindex_required=result.reindex_required,
    )


@router.delete("/{kb_id}", status_code=204)
async def delete_(
    kb_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> None:
    try:
        await delete_knowledge_base(session, ctx, kb_id=kb_id)
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except KnowledgeBaseInUseError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{kb_id}/sources", response_model=list[SourceOut])
async def list_sources_(
    kb_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> list[SourceOut]:
    try:
        views = await list_sources(session, ctx, kb_id=kb_id)
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [
        SourceOut(
            id=str(s.id),
            kb_id=str(s.kb_id),
            type=s.type,
            ingest_status=s.ingest_status,
        )
        for s in views
    ]


@router.delete("/{kb_id}/sources/{source_id}", status_code=204)
async def detach_source_(
    kb_id: UUID,
    source_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> None:
    try:
        await detach_source(session, ctx, kb_id=kb_id, source_id=source_id)
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SourceNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{kb_id}/sources/test-connection")
async def test_connection_(
    kb_id: UUID,
    body: TestConnectionIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> dict[str, Any]:
    # Validate that the KB exists and belongs to the tenant before testing.
    try:
        await get_knowledge_base(session, ctx, kb_id=kb_id)
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    result = await test_source_connection(spec_type=body.type, spec=body.spec)
    return {"ok": result.ok, "error": result.error, "details": result.details}
```

- [ ] **Step 5.2: Mount the router in `backend/src/tfm_rag/infrastructure/api/app.py`**

Replace the imports + `include_router` block:

```python
from fastapi import FastAPI

from tfm_rag.infrastructure.api.middleware.tenant_scoping import (
    TenantScopingMiddleware,
)
from tfm_rag.infrastructure.api.routers import (
    auth,
    credentials,
    health,
    knowledge_bases,
)
from tfm_rag.infrastructure.settings import get_settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="TFM RAG Chatbot Platform",
        version="0.1.0",
    )
    settings = get_settings()
    app.add_middleware(TenantScopingMiddleware, settings=settings)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(credentials.router)
    app.include_router(knowledge_bases.router)
    return app


app = create_app()
```

- [ ] **Step 5.3: ruff + mypy**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
ruff check .
mypy src/
```

Expected: both clean.

- [ ] **Step 5.4: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/infrastructure/api/routers/knowledge_bases.py backend/src/tfm_rag/infrastructure/api/app.py
git commit -m "feat(api): /api/knowledge-bases/* + sources sub-routes"
```

---

## Task 6 — Integration tests

**Files:**
- Create: `backend/tests/integration/test_knowledge_endpoints.py`

- [ ] **Step 6.1: Write the integration test**

Create `backend/tests/integration/test_knowledge_endpoints.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from tfm_rag.infrastructure.api.app import app
from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings


@pytest.fixture
async def _clean_kb_tables(settings: Settings) -> None:
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    async with factory() as s:
        await s.execute(text(
            "TRUNCATE sources, knowledge_bases, "
            "provider_credentials, users, tenants RESTART IDENTITY CASCADE"
        ))
        await s.commit()
    await engine.dispose()


async def _register(client: AsyncClient, email: str) -> tuple[str, str]:
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "correctpassword"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return body["token"], body["tenant_id"]


async def _ollama_credential_id(client: AsyncClient, token: str) -> str:
    r = await client.get(
        "/api/credentials",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    creds = r.json()
    ollama = next(c for c in creds if c["provider_id"] == "ollama")
    return ollama["id"]


@pytest.mark.integration
async def test_kb_full_lifecycle(_clean_kb_tables: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, tenant_id = await _register(client, "kb-user@example.com")
        cred_id = await _ollama_credential_id(client, token)
        h = {"Authorization": f"Bearer {token}"}

        # Create KB
        create = await client.post(
            "/api/knowledge-bases",
            headers=h,
            json={
                "name": "Manuals",
                "description": "User manuals",
                "embedding_selection": {
                    "provider_id": "ollama",
                    "credential_id": cred_id,
                    "model_id": "bge-m3",
                    "dim": 1024,
                },
            },
        )
        assert create.status_code == 201, create.text
        kb = create.json()
        kb_id = kb["id"]
        assert kb["name"] == "Manuals"
        assert kb["embedding_selection"]["dim"] == 1024

        # List
        listed = await client.get("/api/knowledge-bases", headers=h)
        assert listed.status_code == 200
        assert any(item["id"] == kb_id for item in listed.json())

        # Get with sources (empty)
        got = await client.get(f"/api/knowledge-bases/{kb_id}", headers=h)
        assert got.status_code == 200
        body = got.json()
        assert body["kb"]["id"] == kb_id
        assert body["sources"] == []

        # Patch name only — no reindex
        patched = await client.patch(
            f"/api/knowledge-bases/{kb_id}",
            headers=h,
            json={"name": "Manuals v2"},
        )
        assert patched.status_code == 200
        assert patched.json()["kb"]["name"] == "Manuals v2"
        assert patched.json()["reindex_required"] is False

        # Patch embedding dim — reindex required
        patched2 = await client.patch(
            f"/api/knowledge-bases/{kb_id}",
            headers=h,
            json={
                "embedding_selection": {
                    "provider_id": "ollama",
                    "credential_id": cred_id,
                    "model_id": "nomic-embed-text",
                    "dim": 768,
                }
            },
        )
        assert patched2.status_code == 200
        assert patched2.json()["reindex_required"] is True

        # Duplicate name rejected
        dup = await client.post(
            "/api/knowledge-bases",
            headers=h,
            json={
                "name": "Manuals v2",
                "embedding_selection": {
                    "provider_id": "ollama",
                    "credential_id": cred_id,
                    "model_id": "bge-m3",
                    "dim": 1024,
                },
            },
        )
        assert dup.status_code == 400

        # List sources (empty)
        srcs = await client.get(
            f"/api/knowledge-bases/{kb_id}/sources", headers=h
        )
        assert srcs.status_code == 200
        assert srcs.json() == []

        # Test-connection — no tester registered yet
        tc = await client.post(
            f"/api/knowledge-bases/{kb_id}/sources/test-connection",
            headers=h,
            json={"type": "database", "spec": {"driver": "postgres"}},
        )
        assert tc.status_code == 200
        assert tc.json()["ok"] is False
        assert "TESTER_NOT_REGISTERED" in tc.json()["error"]

        # Delete KB
        deleted = await client.delete(
            f"/api/knowledge-bases/{kb_id}", headers=h
        )
        assert deleted.status_code == 204

        # 404 after delete
        missing = await client.get(f"/api/knowledge-bases/{kb_id}", headers=h)
        assert missing.status_code == 404


@pytest.mark.integration
async def test_kb_isolation_between_tenants(_clean_kb_tables: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        alice_token, _ = await _register(client, "alice-kb@example.com")
        bob_token, _ = await _register(client, "bob-kb@example.com")
        alice_cred = await _ollama_credential_id(client, alice_token)

        # Alice creates a KB
        r = await client.post(
            "/api/knowledge-bases",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={
                "name": "Alice KB",
                "embedding_selection": {
                    "provider_id": "ollama",
                    "credential_id": alice_cred,
                    "model_id": "bge-m3",
                    "dim": 1024,
                },
            },
        )
        assert r.status_code == 201
        kb_id = r.json()["id"]

        # Bob cannot see it
        bob_list = await client.get(
            "/api/knowledge-bases",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert bob_list.status_code == 200
        assert bob_list.json() == []

        # Bob cannot fetch by id
        bob_get = await client.get(
            f"/api/knowledge-bases/{kb_id}",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert bob_get.status_code == 404
```

- [ ] **Step 6.2: Reset DB and run the integration tests**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
docker exec tfm-rag-postgres-1 psql -U tfm -d tfm_rag \
  -c "DROP TABLE IF EXISTS sources, knowledge_bases, provider_credentials, users, tenants, alembic_version CASCADE;"
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
alembic upgrade head
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
pytest tests/integration/test_knowledge_endpoints.py -m integration -v
```

Expected: both tests PASS.

- [ ] **Step 6.3: Run the full integration suite to confirm no regressions**

```bash
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
pytest tests/integration -m integration -v
```

Expected: 10+ tests PASS (the original 7 from M1 + 2 new KB tests + 1 migration test).

- [ ] **Step 6.4: Final cleanup pass**

```bash
ruff check .
mypy src/
pytest tests/ -m "not integration"
```

Expected: ruff clean, mypy clean, unit tests pass.

- [ ] **Step 6.5: Commit + tag**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/tests/integration/test_knowledge_endpoints.py
git commit -m "test(knowledge): integration tests for KB lifecycle + tenant isolation"
git tag cap-07-kb-lifecycle
```

---

## What's next (deferred, for handover)

After this plan ships:

- **Plan #8 (CAP-KB-DOC-SOURCES)** picks up `AttachDocumentSource` (upload + cloud), the loader → chunker → embedder pipeline, `IngestSource` / `ReindexSource`, and registers the **document** connection tester (cloud folder reachability) into `SOURCE_CONNECTION_TESTERS`.
- **Plan #9 (CAP-KB-DB-SOURCES)** ships `AttachDatabaseSource` for `postgres` / `mysql`, encrypted connection strings in `source_db_credentials`, and registers the **database** tester.
- **Plan #10 (CAP-CHATBOT-LIFECYCLE)** adds the `chatbots` + `chatbot_knowledge_base` tables with `ON DELETE RESTRICT` on `kb_id`; that wiring is what makes `delete_knowledge_base` actually raise `KnowledgeBaseInUseError` (the catch is already in place here).
- The `reindex_required` flag returned by `update_knowledge_base` is wired to a real reindex side-effect by plan #8 (enqueue `ReindexSource` for every `DocumentSource` of the KB).
