# CAP-INTEG-CREDENTIALS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Provider catalog (in code) + `ProviderCredential` table/ORM/entity + CRUD use cases + API endpoints. After this plan, an admin can register/test/delete API keys for OpenAI, OpenAI-compat providers. Also: complete `BootstrapTenant` to create the Ollama default credential.

**Architecture:** The catalog lives in `domain/catalog/llm_providers.py` (and `embedding_providers.py`) as a Python dict — NO superadmin runtime. `ProviderCredential` rows are encrypted with `FernetSecretEncryptor` (plan #3) before persisting. `TestCredential` issues a small request against the provider with the decrypted key.

**Tech Stack:** No new deps beyond what plans 1-5 already added.

**Depends on:** Plan #1 (engine, settings), Plan #2 (TenantScopingMiddleware, BaseRepository), Plan #3 (FernetSecretEncryptor), Plan #5 (BootstrapTenant — extended here).

---

## File structure

```
backend/src/tfm_rag/
├── domain/
│   ├── catalog/
│   │   ├── __init__.py
│   │   ├── llm_providers.py        # LLMProviderDescriptor + LLM_PROVIDER_CATALOG
│   │   └── embedding_providers.py
│   └── entities/
│       └── provider_credential.py
├── infrastructure/
│   └── persistence/
│       ├── models/
│       │   └── provider_credentials.py
│       └── repositories/
│           └── credentials_repo.py
└── application/
    └── integrations/
        ├── __init__.py
        ├── upsert_provider_credential.py
        ├── list_credentials.py
        ├── delete_credential.py
        └── test_credential.py

backend/alembic/versions/
└── 0003_provider_credentials.py

backend/src/tfm_rag/infrastructure/api/routers/
└── credentials.py

backend/tests/unit/
└── test_credentials_use_cases.py
```

---

## Task 1 — Provider catalog

### Step 1.1: Create `backend/src/tfm_rag/domain/catalog/__init__.py` (empty)

### Step 1.2: Create `backend/src/tfm_rag/domain/catalog/llm_providers.py`

```python
from dataclasses import dataclass, field
from typing import Literal


ConfigSource = Literal["SERVER_ENV", "TENANT_CREDENTIAL"]


@dataclass(frozen=True, slots=True)
class LLMProviderDescriptor:
    id: str
    display_name: str
    description: str
    config_source: ConfigSource
    requires_base_url_input: bool
    supports_tool_calling: bool
    default_models: tuple[str, ...] = field(default_factory=tuple)


LLM_PROVIDER_CATALOG: dict[str, LLMProviderDescriptor] = {
    "ollama": LLMProviderDescriptor(
        id="ollama",
        display_name="Ollama (local)",
        description="Local LLM via Ollama. Configured via OLLAMA_BASE_URL env.",
        config_source="SERVER_ENV",
        requires_base_url_input=False,
        supports_tool_calling=True,
        default_models=("llama3.1", "mistral", "gemma2"),
    ),
    "openai": LLMProviderDescriptor(
        id="openai",
        display_name="OpenAI",
        description="OpenAI chat completions API.",
        config_source="TENANT_CREDENTIAL",
        requires_base_url_input=False,
        supports_tool_calling=True,
        default_models=("gpt-4o-mini", "gpt-4o"),
    ),
    "openai_compat": LLMProviderDescriptor(
        id="openai_compat",
        display_name="OpenAI-compatible endpoint",
        description=(
            "Any provider exposing a Chat Completions-compatible API "
            "(Groq, Together, OpenRouter, DeepSeek, NIM, GitHub Models, ...)."
        ),
        config_source="TENANT_CREDENTIAL",
        requires_base_url_input=True,
        supports_tool_calling=True,
        default_models=(),
    ),
}
```

### Step 1.3: Create `backend/src/tfm_rag/domain/catalog/embedding_providers.py`

```python
from dataclasses import dataclass

from tfm_rag.domain.catalog.llm_providers import ConfigSource


@dataclass(frozen=True, slots=True)
class EmbeddingProviderDescriptor:
    id: str
    display_name: str
    description: str
    config_source: ConfigSource
    requires_base_url_input: bool
    default_models: tuple[tuple[str, int], ...]  # (model_id, dim)


EMBEDDING_PROVIDER_CATALOG: dict[str, EmbeddingProviderDescriptor] = {
    "ollama": EmbeddingProviderDescriptor(
        id="ollama",
        display_name="Ollama (local)",
        description="Local embeddings via Ollama.",
        config_source="SERVER_ENV",
        requires_base_url_input=False,
        default_models=(
            ("bge-m3", 1024),
            ("nomic-embed-text", 768),
            ("embeddinggemma:300m", 768),
        ),
    ),
    "openai_compat": EmbeddingProviderDescriptor(
        id="openai_compat",
        display_name="OpenAI (or compatible)",
        description="OpenAI embeddings or any compatible endpoint.",
        config_source="TENANT_CREDENTIAL",
        requires_base_url_input=False,
        default_models=(
            ("text-embedding-3-small", 1536),
            ("text-embedding-3-large", 3072),
        ),
    ),
}
```

### Step 1.4: Commit

```bash
git add backend/src/tfm_rag/domain/catalog/
git commit -m "feat(domain): provider catalog (LLM + embedding descriptors)"
```

---

## Task 2 — Entity + ORM + migration 0003

### Step 2.1: Create `backend/src/tfm_rag/domain/entities/provider_credential.py`

```python
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tfm_rag.domain.catalog.llm_providers import ConfigSource


@dataclass(frozen=True, slots=True)
class ProviderCredential:
    id: UUID
    tenant_id: UUID
    provider_id: str
    label: str
    api_key_encrypted: bytes
    base_url: str | None
    config_source: ConfigSource
    created_at: datetime
    updated_at: datetime
```

### Step 2.2: Create `backend/src/tfm_rag/infrastructure/persistence/models/provider_credentials.py`

```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from tfm_rag.infrastructure.persistence.base import Base


class ProviderCredentialRow(Base):
    __tablename__ = "provider_credentials"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider_id", "label",
            name="uq_provider_credentials_tenant_provider_label",
        ),
        CheckConstraint(
            "config_source IN ('SERVER_ENV','TENANT_CREDENTIAL')",
            name="ck_provider_credentials_config_source",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_id: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    config_source: Mapped[str] = mapped_column(String(32), nullable=False)
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

### Step 2.3: Create `backend/alembic/versions/0003_provider_credentials.py`

```python
"""create provider_credentials table

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-20 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_id", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("api_key_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("config_source", sa.String(length=32), nullable=False),
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
            "tenant_id", "provider_id", "label",
            name="uq_provider_credentials_tenant_provider_label",
        ),
        sa.CheckConstraint(
            "config_source IN ('SERVER_ENV','TENANT_CREDENTIAL')",
            name="ck_provider_credentials_config_source",
        ),
    )
    op.create_index(
        "ix_provider_credentials_tenant_id",
        "provider_credentials",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_provider_credentials_tenant_id", table_name="provider_credentials"
    )
    op.drop_table("provider_credentials")
```

### Step 2.4: Update `backend/alembic/env.py` to import the new model

Find the imports block that lists model modules (after `from tfm_rag.infrastructure.persistence.base import Base`) and append:

```python
from tfm_rag.infrastructure.persistence.models import provider_credentials  # noqa: F401
```

### Step 2.5: Commit

```bash
git add backend/src/tfm_rag/domain/entities/provider_credential.py \
        backend/src/tfm_rag/infrastructure/persistence/models/provider_credentials.py \
        backend/alembic/versions/0003_provider_credentials.py \
        backend/alembic/env.py
git commit -m "feat(infra): ProviderCredential entity + ORM + migration 0003"
```

---

## Task 3 — Repository + use cases

### Step 3.1: Create `backend/src/tfm_rag/infrastructure/persistence/repositories/credentials_repo.py`

```python
from sqlalchemy import select

from tfm_rag.infrastructure.persistence.models.provider_credentials import (
    ProviderCredentialRow,
)
from tfm_rag.infrastructure.persistence.repository import BaseRepository


class ProviderCredentialRepository(BaseRepository[ProviderCredentialRow]):
    model = ProviderCredentialRow

    async def find_by_provider_id(
        self, provider_id: str
    ) -> list[ProviderCredentialRow]:
        stmt = (
            select(ProviderCredentialRow)
            .where(
                ProviderCredentialRow.tenant_id == self._ctx.tenant_id,
                ProviderCredentialRow.provider_id == provider_id,
            )
        )
        return list((await self._session.execute(stmt)).scalars().all())
```

### Step 3.2: Create `backend/src/tfm_rag/application/integrations/__init__.py` (empty)

### Step 3.3: Create `backend/src/tfm_rag/application/integrations/upsert_provider_credential.py`

```python
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.catalog.llm_providers import LLM_PROVIDER_CATALOG
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.ports.secret_encryptor import SecretEncryptor
from tfm_rag.infrastructure.persistence.models.provider_credentials import (
    ProviderCredentialRow,
)
from tfm_rag.infrastructure.persistence.repositories.credentials_repo import (
    ProviderCredentialRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext


@dataclass(frozen=True, slots=True)
class UpsertResult:
    id: UUID
    provider_id: str
    label: str


async def upsert_provider_credential(
    session: AsyncSession,
    ctx: RequestContext,
    encryptor: SecretEncryptor,
    *,
    provider_id: str,
    label: str,
    api_key: str,
    base_url: str | None = None,
) -> UpsertResult:
    descriptor = LLM_PROVIDER_CATALOG.get(provider_id)
    if descriptor is None:
        raise ValidationError(f"Unknown provider_id: {provider_id}")
    if descriptor.config_source != "TENANT_CREDENTIAL":
        raise ValidationError(
            f"Provider {provider_id} is configured via {descriptor.config_source}; "
            "credentials are not stored per-tenant."
        )
    if descriptor.requires_base_url_input and not base_url:
        raise ValidationError(
            f"Provider {provider_id} requires a base_url"
        )

    repo = ProviderCredentialRepository(session, ctx)
    row = ProviderCredentialRow(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        provider_id=provider_id,
        label=label,
        api_key_encrypted=encryptor.encrypt(api_key.encode("utf-8")),
        base_url=base_url,
        config_source="TENANT_CREDENTIAL",
    )
    await repo.add(row)
    return UpsertResult(id=row.id, provider_id=row.provider_id, label=row.label)
```

### Step 3.4: Create `backend/src/tfm_rag/application/integrations/list_credentials.py`

```python
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.infrastructure.persistence.repositories.credentials_repo import (
    ProviderCredentialRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext


@dataclass(frozen=True, slots=True)
class CredentialView:
    id: UUID
    provider_id: str
    label: str
    base_url: str | None
    config_source: str
    created_at: datetime


async def list_credentials(
    session: AsyncSession,
    ctx: RequestContext,
) -> list[CredentialView]:
    repo = ProviderCredentialRepository(session, ctx)
    rows = await repo.list(limit=200, offset=0)
    return [
        CredentialView(
            id=r.id,
            provider_id=r.provider_id,
            label=r.label,
            base_url=r.base_url,
            config_source=r.config_source,
            created_at=r.created_at,
        )
        for r in rows
    ]
```

### Step 3.5: Create `backend/src/tfm_rag/application/integrations/delete_credential.py`

```python
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.infrastructure.persistence.repositories.credentials_repo import (
    ProviderCredentialRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext


async def delete_credential(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    credential_id: UUID,
) -> None:
    repo = ProviderCredentialRepository(session, ctx)
    await repo.delete(credential_id)
```

### Step 3.6: Create `backend/src/tfm_rag/application/integrations/test_credential.py`

```python
from dataclasses import dataclass
from time import perf_counter
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.catalog.llm_providers import LLM_PROVIDER_CATALOG
from tfm_rag.domain.errors.integrations import CredentialNotFoundError
from tfm_rag.domain.ports.secret_encryptor import SecretEncryptor
from tfm_rag.infrastructure.persistence.repositories.credentials_repo import (
    ProviderCredentialRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext


@dataclass(frozen=True, slots=True)
class TestCredentialResult:
    ok: bool
    latency_ms: int
    error: str | None


async def test_credential(
    session: AsyncSession,
    ctx: RequestContext,
    encryptor: SecretEncryptor,
    *,
    credential_id: UUID,
    model_id: str,
) -> TestCredentialResult:
    repo = ProviderCredentialRepository(session, ctx)
    try:
        row = await repo.get(credential_id)
    except Exception as exc:
        raise CredentialNotFoundError(str(exc)) from exc

    descriptor = LLM_PROVIDER_CATALOG[row.provider_id]
    api_key = encryptor.decrypt(row.api_key_encrypted).decode("utf-8")
    base = row.base_url or "https://api.openai.com/v1"
    if descriptor.id == "openai":
        base = "https://api.openai.com/v1"

    started = perf_counter()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{base.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        latency = int((perf_counter() - started) * 1000)
        return TestCredentialResult(ok=False, latency_ms=latency, error=str(exc)[:200])
    latency = int((perf_counter() - started) * 1000)
    return TestCredentialResult(ok=True, latency_ms=latency, error=None)
```

### Step 3.7: Commit

```bash
git add backend/src/tfm_rag/infrastructure/persistence/repositories/credentials_repo.py \
        backend/src/tfm_rag/application/integrations/
git commit -m "feat(integrations): ProviderCredential repo + CRUD use cases"
```

---

## Task 4 — API routers

### Step 4.1: Create `backend/src/tfm_rag/infrastructure/api/routers/credentials.py`

```python
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.integrations.delete_credential import delete_credential
from tfm_rag.application.integrations.list_credentials import (
    CredentialView,
    list_credentials,
)
from tfm_rag.application.integrations.test_credential import test_credential
from tfm_rag.application.integrations.upsert_provider_credential import (
    upsert_provider_credential,
)
from tfm_rag.domain.catalog.embedding_providers import (
    EMBEDDING_PROVIDER_CATALOG,
)
from tfm_rag.domain.catalog.llm_providers import (
    LLM_PROVIDER_CATALOG,
    LLMProviderDescriptor,
)
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.errors.integrations import CredentialNotFoundError
from tfm_rag.infrastructure.api.dependencies import (
    get_current_context,
    get_session,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.secrets.fernet_encryptor import FernetSecretEncryptor
from tfm_rag.infrastructure.settings import Settings, get_settings


router = APIRouter(prefix="/api", tags=["integrations"])


class UpsertIn(BaseModel):
    provider_id: str
    label: str
    api_key: str
    base_url: str | None = None


class TestIn(BaseModel):
    model_id: str


class CredentialOut(BaseModel):
    id: str
    provider_id: str
    label: str
    base_url: str | None
    config_source: str

    @classmethod
    def from_view(cls, v: CredentialView) -> "CredentialOut":
        return cls(
            id=str(v.id),
            provider_id=v.provider_id,
            label=v.label,
            base_url=v.base_url,
            config_source=v.config_source,
        )


@router.get("/providers/llm")
async def list_llm_providers() -> list[LLMProviderDescriptor]:
    return list(LLM_PROVIDER_CATALOG.values())


@router.get("/providers/embedding")
async def list_embedding_providers() -> list[dict[str, object]]:
    return [
        {
            "id": d.id,
            "display_name": d.display_name,
            "description": d.description,
            "config_source": d.config_source,
            "requires_base_url_input": d.requires_base_url_input,
            "default_models": d.default_models,
        }
        for d in EMBEDDING_PROVIDER_CATALOG.values()
    ]


@router.get("/credentials")
async def list_(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> list[CredentialOut]:
    views = await list_credentials(session, ctx)
    return [CredentialOut.from_view(v) for v in views]


@router.post("/credentials", status_code=201)
async def create_(
    body: UpsertIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> CredentialOut:
    encryptor = FernetSecretEncryptor(settings.fernet_key)
    try:
        result = await upsert_provider_credential(
            session,
            ctx,
            encryptor,
            provider_id=body.provider_id,
            label=body.label,
            api_key=body.api_key,
            base_url=body.base_url,
        )
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return CredentialOut(
        id=str(result.id),
        provider_id=result.provider_id,
        label=result.label,
        base_url=body.base_url,
        config_source="TENANT_CREDENTIAL",
    )


@router.delete("/credentials/{credential_id}", status_code=204)
async def delete_(
    credential_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> None:
    try:
        await delete_credential(session, ctx, credential_id=credential_id)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post("/credentials/{credential_id}/test")
async def test_(
    credential_id: UUID,
    body: TestIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> dict[str, object]:
    encryptor = FernetSecretEncryptor(settings.fernet_key)
    try:
        result = await test_credential(
            session,
            ctx,
            encryptor,
            credential_id=credential_id,
            model_id=body.model_id,
        )
    except CredentialNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return {
        "ok": result.ok,
        "latency_ms": result.latency_ms,
        "error": result.error,
    }
```

### Step 4.2: Register the router in `backend/src/tfm_rag/infrastructure/api/app.py`

In `create_app()`, alongside the existing routers, add:

```python
from tfm_rag.infrastructure.api.routers import auth, credentials, health
```

And:

```python
app.include_router(credentials.router)
```

### Step 4.3: Commit

```bash
git add backend/src/tfm_rag/infrastructure/api/routers/credentials.py \
        backend/src/tfm_rag/infrastructure/api/app.py
git commit -m "feat(integrations): /api/credentials + /api/providers/* routers"
```

---

## Task 5 — Extend `BootstrapTenant` to create Ollama default credential

### Step 5.1: Modify `backend/src/tfm_rag/application/auth/bootstrap_tenant.py`

Replace the existing body with:

```python
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.infrastructure.persistence.models.provider_credentials import (
    ProviderCredentialRow,
)
from tfm_rag.infrastructure.persistence.models.tenants import TenantRow


@dataclass(frozen=True, slots=True)
class BootstrapTenantResult:
    tenant_id: UUID
    qdrant_collection_prefix: str
    storage_prefix: str


async def bootstrap_tenant(
    session: AsyncSession,
    *,
    name: str,
) -> BootstrapTenantResult:
    """Create a fresh Tenant row + a default Ollama ProviderCredential row.

    The Ollama credential has `config_source=SERVER_ENV` so it doesn't store
    an API key (Ollama doesn't require one); the field carries a sentinel
    encrypted value. The `base_url` is left NULL — the adapter reads
    `OLLAMA_BASE_URL` from Settings.
    """
    tenant_id = uuid4()
    prefix = f"kb_chunks__{tenant_id}"
    storage = f"tenant_{tenant_id}/"
    tenant = TenantRow(
        id=tenant_id,
        name=name,
        qdrant_collection_prefix=prefix,
        storage_prefix=storage,
    )
    session.add(tenant)

    ollama_default = ProviderCredentialRow(
        id=uuid4(),
        tenant_id=tenant_id,
        provider_id="ollama",
        label="default",
        # SERVER_ENV: no real api_key. We store a sentinel bytes value to satisfy NOT NULL.
        api_key_encrypted=b"server-env-sentinel",
        base_url=None,
        config_source="SERVER_ENV",
    )
    session.add(ollama_default)

    await session.flush()
    return BootstrapTenantResult(
        tenant_id=tenant_id,
        qdrant_collection_prefix=prefix,
        storage_prefix=storage,
    )
```

### Step 5.2: Commit

```bash
git add backend/src/tfm_rag/application/auth/bootstrap_tenant.py
git commit -m "feat(auth): BootstrapTenant also creates Ollama default credential"
```

---

## Task 6 — Tag

```bash
git tag cap-06-integ-credentials
```

---

## Done criteria

- Provider catalogs registered (LLM + Embedding).
- `provider_credentials` table migrated (0003).
- CRUD + Test endpoints under `/api/credentials` and `/api/providers/*`.
- BootstrapTenant creates the Ollama default credential.
- Tag `cap-06-integ-credentials`.

**M1 milestone complete after this plan.** Docker compose up + register → user lands in dashboard with Ollama default available; can configure additional providers via Settings → Integraciones.
