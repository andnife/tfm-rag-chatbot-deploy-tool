# CAP-INFRA-TENANT-ISOLATION Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the User + Tenant ORM models, the tenant-scoped repository CRUD layer, the JWT-based tenant scoping middleware, and the `TenantScopeViolation` invariant. After this plan, repositories filter by `tenant_id` automatically and the system rejects cross-tenant access.

**Architecture:** Tenant isolation is enforced at three layers in defense-in-depth: (1) HTTP middleware extracts `tenant_id` from the JWT and pins it into a `RequestContext`; (2) every repository receives that context and filters all queries by `tenant_id`; (3) ORM models carry a `tenant_id` column with a NOT NULL constraint. Qdrant collections are physically separated per `(tenant, dim)` (already implemented in plan #1 via `collection_name_for`).

**Tech Stack:** SQLAlchemy 2.0 typed ORM, Alembic, FastAPI middleware, python-jose for JWT.

**Depends on:** Plan #1 (`CAP-INFRA-PERSISTENCE`) — uses `Base`, `BaseRepository`, `RequestContext`, `build_engine`, `Settings`.

---

## File structure for this plan

**Created:**

```
backend/src/tfm_rag/
├── domain/
│   ├── entities/
│   │   ├── __init__.py
│   │   ├── tenant.py             # Tenant entity (domain)
│   │   └── user.py               # User entity (domain)
│   └── errors/
│       └── common.py             # add TenantScopeViolation
├── infrastructure/
│   ├── auth/
│   │   ├── __init__.py
│   │   └── jwt.py                # JWT encode/decode helpers
│   ├── api/
│   │   ├── dependencies.py       # get_session, get_current_context
│   │   └── middleware/
│   │       ├── __init__.py
│   │       └── tenant_scoping.py # TenantScopingMiddleware
│   └── persistence/
│       ├── models/
│       │   ├── __init__.py
│       │   ├── tenants.py        # SQLAlchemy ORM: TenantRow
│       │   └── users.py          # SQLAlchemy ORM: UserRow
│       └── repository.py         # add tenant-aware CRUD to BaseRepository

backend/alembic/versions/
└── 0002_users_tenants.py         # migration: tenants + users tables

backend/tests/unit/
├── test_jwt.py
└── test_tenant_scoping_middleware.py

backend/tests/integration/
├── test_users_tenants_migration.py
└── test_repository_tenant_isolation.py
```

**Responsibilities:**
- `domain/entities/tenant.py` and `domain/entities/user.py`: pure dataclasses (no SQLAlchemy) representing the domain model.
- `infrastructure/persistence/models/tenants.py` and `.../users.py`: SQLAlchemy ORM mapping, separate from domain.
- `infrastructure/persistence/repository.py`: extends `BaseRepository[E]` with `add`, `get`, `list`, `delete` methods that automatically filter by `ctx.tenant_id`.
- `infrastructure/auth/jwt.py`: `encode_jwt(payload, secret, expires_hours)` and `decode_jwt(token, secret) -> dict`.
- `infrastructure/api/middleware/tenant_scoping.py`: ASGI middleware that pulls `Authorization: Bearer <jwt>`, decodes, attaches `RequestContext(tenant_id, user_id)` to `request.state`.
- `infrastructure/api/dependencies.py`: FastAPI deps for session and context.
- `alembic/versions/0002_users_tenants.py`: creates `tenants` and `users` tables per spec §9.
- `domain/errors/common.py`: add `TenantScopeViolation`.

---

## Task 1 — Domain entities (User, Tenant)

**Files:**
- Create: `backend/src/tfm_rag/domain/entities/__init__.py`
- Create: `backend/src/tfm_rag/domain/entities/tenant.py`
- Create: `backend/src/tfm_rag/domain/entities/user.py`

- [ ] **Step 1.1: Create `backend/src/tfm_rag/domain/entities/__init__.py`**

Empty file.

- [ ] **Step 1.2: Create `backend/src/tfm_rag/domain/entities/tenant.py`**

```python
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Tenant:
    id: UUID
    name: str
    qdrant_collection_prefix: str
    storage_prefix: str
    created_at: datetime
```

- [ ] **Step 1.3: Create `backend/src/tfm_rag/domain/entities/user.py`**

```python
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    email: str
    password_hash: str | None
    google_sub: str | None
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 1.4: Commit**

```bash
git add backend/src/tfm_rag/domain/entities/
git commit -m "feat(domain): User and Tenant entities"
```

---

## Task 2 — Add `TenantScopeViolation` error

**Files:**
- Create: `backend/src/tfm_rag/domain/errors/common.py`

- [ ] **Step 2.1: Create `backend/src/tfm_rag/domain/errors/common.py`**

```python
class DomainError(Exception):
    """Base class for all domain-level errors."""


class NotFoundError(DomainError):
    """Raised when a resource is not found."""


class ValidationError(DomainError):
    """Raised when input validation fails at the domain level."""


class TenantScopeViolation(DomainError):
    """Raised when a use case tries to access data from a different tenant.

    This should NEVER happen in correctly-written code; if it triggers,
    something at the application layer is bypassing the repository pattern.
    """
```

- [ ] **Step 2.2: Commit**

```bash
git add backend/src/tfm_rag/domain/errors/common.py
git commit -m "feat(domain): base errors + TenantScopeViolation"
```

---

## Task 3 — SQLAlchemy ORM models (TenantRow, UserRow)

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/persistence/models/__init__.py`
- Create: `backend/src/tfm_rag/infrastructure/persistence/models/tenants.py`
- Create: `backend/src/tfm_rag/infrastructure/persistence/models/users.py`

- [ ] **Step 3.1: Create `models/__init__.py`** (empty)

- [ ] **Step 3.2: Create `models/tenants.py`**

```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from tfm_rag.infrastructure.persistence.base import Base


class TenantRow(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    qdrant_collection_prefix: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    storage_prefix: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 3.3: Create `models/users.py`**

```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from tfm_rag.infrastructure.persistence.base import Base


class UserRow(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("google_sub", name="uq_users_google_sub"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
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

- [ ] **Step 3.4: Commit**

```bash
git add backend/src/tfm_rag/infrastructure/persistence/models/
git commit -m "feat(infra): SQLAlchemy ORM models for tenants and users"
```

---

## Task 4 — Alembic migration 0002 (tenants + users tables)

**Files:**
- Create: `backend/alembic/versions/0002_users_tenants.py`

- [ ] **Step 4.1: Create the migration**

```python
"""create tenants and users tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-20 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "qdrant_collection_prefix",
            sa.String(length=255),
            unique=True,
            nullable=False,
        ),
        sa.Column(
            "storage_prefix",
            sa.String(length=255),
            unique=True,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("google_sub", sa.String(length=255), nullable=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("google_sub", name="uq_users_google_sub"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_table("users")
    op.drop_table("tenants")
```

- [ ] **Step 4.2: Update `alembic/env.py` to import all model modules so `Base.metadata` is populated**

Read `backend/alembic/env.py` and locate the line `target_metadata = Base.metadata`. ABOVE that line, add:

```python
# Import all ORM model modules so Base.metadata sees them for autogenerate
from tfm_rag.infrastructure.persistence.models import tenants  # noqa: F401
from tfm_rag.infrastructure.persistence.models import users  # noqa: F401
```

- [ ] **Step 4.3: Commit**

```bash
git add backend/alembic/versions/0002_users_tenants.py backend/alembic/env.py
git commit -m "feat(infra): migration 0002 — tenants and users tables"
```

---

## Task 5 — Tenant-aware `BaseRepository` (add, get, list, delete)

**Files:**
- Modify: `backend/src/tfm_rag/infrastructure/persistence/repository.py`

- [ ] **Step 5.1: Rewrite `repository.py`**

```python
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.common import NotFoundError, TenantScopeViolation
from tfm_rag.infrastructure.persistence.base import Base


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Carries the authenticated tenant/user for the lifetime of a request."""
    tenant_id: UUID
    user_id: UUID | None = None


class BaseRepository[E: Base]:
    """Generic tenant-aware repository.

    Subclasses MUST set `model = <ORM class>` AND that ORM class MUST have a
    `tenant_id` column (defense in depth: every model under tenant scoping
    carries the column directly).
    """

    model: ClassVar[type]

    def __init__(self, session: AsyncSession, ctx: RequestContext) -> None:
        self._session = session
        self._ctx = ctx

    def _check_tenant(self, row: object) -> None:
        row_tenant = getattr(row, "tenant_id", None)
        if row_tenant is None:
            raise TenantScopeViolation(
                f"{type(row).__name__} has no tenant_id; refusing to operate."
            )
        if row_tenant != self._ctx.tenant_id:
            raise TenantScopeViolation(
                f"Row tenant {row_tenant!s} != context tenant {self._ctx.tenant_id!s}."
            )

    async def add(self, row: E) -> E:
        """Persist a row. Caller must set row.tenant_id = ctx.tenant_id."""
        self._check_tenant(row)
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, row_id: UUID) -> E:
        stmt = select(self.model).where(
            self.model.id == row_id,  # type: ignore[attr-defined]
            self.model.tenant_id == self._ctx.tenant_id,  # type: ignore[attr-defined]
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"{self.model.__name__}({row_id}) not found in tenant")
        return row

    async def list(self, *, limit: int = 20, offset: int = 0) -> list[E]:
        stmt = (
            select(self.model)
            .where(self.model.tenant_id == self._ctx.tenant_id)  # type: ignore[attr-defined]
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, row_id: UUID) -> None:
        stmt = delete(self.model).where(
            self.model.id == row_id,  # type: ignore[attr-defined]
            self.model.tenant_id == self._ctx.tenant_id,  # type: ignore[attr-defined]
        )
        result = await self._session.execute(stmt)
        if result.rowcount == 0:
            raise NotFoundError(f"{self.model.__name__}({row_id}) not found in tenant")
```

**Note:** This file REPLACES the previous skeleton from plan #1. Any code that imported the skeleton will continue to work because the public interface (`RequestContext`, `BaseRepository`) is preserved.

- [ ] **Step 5.2: Commit**

```bash
git add backend/src/tfm_rag/infrastructure/persistence/repository.py
git commit -m "feat(infra): tenant-aware BaseRepository CRUD methods"
```

---

## Task 6 — JWT encode/decode helpers

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/auth/__init__.py`
- Create: `backend/src/tfm_rag/infrastructure/auth/jwt.py`

- [ ] **Step 6.1: Add `python-jose` dependency**

Modify `backend/pyproject.toml`, add to `dependencies`:

```toml
"python-jose[cryptography]>=3.3",
```

(Place it alphabetically near the other auth-related libs; for simplicity, append before `structlog`.)

- [ ] **Step 6.2: Re-install dev deps**

```bash
cd backend
source .venv/bin/activate
pip install -e ".[dev]"
```

- [ ] **Step 6.3: Create `auth/__init__.py`** (empty)

- [ ] **Step 6.4: Create `auth/jwt.py`**

```python
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from jose import JWTError, jwt

from tfm_rag.domain.errors.common import DomainError


class TokenInvalidError(DomainError):
    """Raised when a JWT is missing, malformed, or expired."""


def encode_jwt(
    *,
    user_id: UUID,
    tenant_id: UUID,
    secret: str,
    expires_hours: int,
) -> str:
    """Create a signed JWT (HS256) carrying user_id and tenant_id."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=expires_hours)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_jwt(token: str, secret: str) -> dict[str, Any]:
    """Verify signature + expiration. Returns the payload dict.

    Raises TokenInvalidError on any failure (expired, bad signature, malformed).
    """
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except JWTError as exc:
        raise TokenInvalidError(str(exc)) from exc
```

- [ ] **Step 6.5: Create unit test `backend/tests/unit/test_jwt.py`**

```python
from uuid import uuid4

import pytest

from tfm_rag.infrastructure.auth.jwt import (
    TokenInvalidError,
    decode_jwt,
    encode_jwt,
)


SECRET = "x" * 32


def test_encode_decode_roundtrip() -> None:
    user_id = uuid4()
    tenant_id = uuid4()
    token = encode_jwt(
        user_id=user_id, tenant_id=tenant_id, secret=SECRET, expires_hours=24
    )
    payload = decode_jwt(token, SECRET)
    assert payload["sub"] == str(user_id)
    assert payload["tid"] == str(tenant_id)
    assert payload["exp"] > payload["iat"]


def test_decode_with_wrong_secret_raises() -> None:
    token = encode_jwt(
        user_id=uuid4(), tenant_id=uuid4(), secret=SECRET, expires_hours=24
    )
    with pytest.raises(TokenInvalidError):
        decode_jwt(token, "y" * 32)


def test_decode_malformed_raises() -> None:
    with pytest.raises(TokenInvalidError):
        decode_jwt("not-a-jwt", SECRET)
```

- [ ] **Step 6.6: Commit**

```bash
git add backend/pyproject.toml backend/src/tfm_rag/infrastructure/auth/ \
        backend/tests/unit/test_jwt.py
git commit -m "feat(auth): JWT encode/decode helpers + tests"
```

---

## Task 7 — Tenant scoping middleware

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/api/middleware/__init__.py`
- Create: `backend/src/tfm_rag/infrastructure/api/middleware/tenant_scoping.py`

- [ ] **Step 7.1: Create `middleware/__init__.py`** (empty)

- [ ] **Step 7.2: Create `middleware/tenant_scoping.py`**

```python
from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from tfm_rag.infrastructure.auth.jwt import TokenInvalidError, decode_jwt
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.settings import Settings


# Paths that do NOT require an authenticated context.
UNAUTHENTICATED_PREFIXES: tuple[str, ...] = (
    "/api/auth/",
    "/api/public/",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
)


class TenantScopingMiddleware(BaseHTTPMiddleware):
    """Extracts tenant_id and user_id from the JWT and attaches them to
    `request.state.ctx`. If the path is unauthenticated, sets ctx to None.
    """

    def __init__(self, app: Callable[..., Awaitable[Response]], *, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if any(path.startswith(p) for p in UNAUTHENTICATED_PREFIXES):
            request.state.ctx = None
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return Response(
                content='{"error":{"code":"unauthenticated","message":"Missing Bearer token"}}',
                status_code=401,
                media_type="application/json",
            )
        token = auth.split(" ", 1)[1].strip()
        try:
            payload = decode_jwt(token, self._settings.jwt_secret)
        except TokenInvalidError as exc:
            return Response(
                content=f'{{"error":{{"code":"unauthenticated","message":"{exc}"}}}}',
                status_code=401,
                media_type="application/json",
            )

        request.state.ctx = RequestContext(
            tenant_id=UUID(payload["tid"]),
            user_id=UUID(payload["sub"]),
        )
        return await call_next(request)
```

- [ ] **Step 7.3: Unit test `backend/tests/unit/test_tenant_scoping_middleware.py`**

```python
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from tfm_rag.infrastructure.api.middleware.tenant_scoping import (
    TenantScopingMiddleware,
)
from tfm_rag.infrastructure.auth.jwt import encode_jwt
from tfm_rag.infrastructure.settings import Settings


SECRET = "x" * 32


def _build_app(settings: Settings) -> FastAPI:
    app = FastAPI()
    app.add_middleware(TenantScopingMiddleware, settings=settings)

    @app.get("/api/me")
    async def me(request: Request) -> dict[str, str | None]:
        ctx = request.state.ctx
        return {
            "tenant_id": str(ctx.tenant_id) if ctx else None,
            "user_id": str(ctx.user_id) if ctx else None,
        }

    @app.get("/api/public/anything")
    async def public(request: Request) -> dict[str, str | None]:
        return {"ctx": "none" if request.state.ctx is None else "set"}

    return app


@pytest.fixture
def jwt_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://u:p@h:5432/d")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setenv(
        "FERNET_KEY", "X4O7zPlk-AbCdEfGhIjKlMnOpQrStUvWxYz0123456="
    )
    return Settings()  # type: ignore[call-arg]


async def test_authenticated_request_sets_ctx(jwt_settings: Settings) -> None:
    user_id = uuid4()
    tenant_id = uuid4()
    token = encode_jwt(
        user_id=user_id, tenant_id=tenant_id, secret=SECRET, expires_hours=24
    )
    app = _build_app(jwt_settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == {"tenant_id": str(tenant_id), "user_id": str(user_id)}


async def test_missing_token_returns_401(jwt_settings: Settings) -> None:
    app = _build_app(jwt_settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/me")
    assert r.status_code == 401


async def test_public_path_passes_without_token(jwt_settings: Settings) -> None:
    app = _build_app(jwt_settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/public/anything")
    assert r.status_code == 200
    assert r.json() == {"ctx": "none"}


async def test_bad_token_returns_401(jwt_settings: Settings) -> None:
    app = _build_app(jwt_settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/me", headers={"Authorization": "Bearer not-a-jwt"}
        )
    assert r.status_code == 401
```

- [ ] **Step 7.4: Commit**

```bash
git add backend/src/tfm_rag/infrastructure/api/middleware/ \
        backend/tests/unit/test_tenant_scoping_middleware.py
git commit -m "feat(infra): TenantScopingMiddleware + tests"
```

---

## Task 8 — Wire middleware into FastAPI app + dependencies

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/api/dependencies.py`
- Modify: `backend/src/tfm_rag/infrastructure/api/app.py`

- [ ] **Step 8.1: Create `dependencies.py`**

```python
from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.settings import Settings, get_settings


_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        engine = build_engine(settings.postgres_url)
        _session_factory = build_session_factory(engine)
    return _session_factory


async def get_session(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AsyncIterator[AsyncSession]:
    factory = _get_factory(settings)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_current_context(request: Request) -> RequestContext:
    ctx: RequestContext | None = getattr(request.state, "ctx", None)
    if ctx is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return ctx
```

- [ ] **Step 8.2: Modify `app.py` to register the middleware**

Replace `app.py` content with:

```python
from fastapi import FastAPI

from tfm_rag.infrastructure.api.middleware.tenant_scoping import (
    TenantScopingMiddleware,
)
from tfm_rag.infrastructure.api.routers import health
from tfm_rag.infrastructure.settings import get_settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="TFM RAG Chatbot Platform",
        version="0.1.0",
    )
    settings = get_settings()
    app.add_middleware(TenantScopingMiddleware, settings=settings)
    app.include_router(health.router)
    return app


app = create_app()
```

- [ ] **Step 8.3: Commit**

```bash
git add backend/src/tfm_rag/infrastructure/api/dependencies.py \
        backend/src/tfm_rag/infrastructure/api/app.py
git commit -m "feat(infra): wire TenantScopingMiddleware + session/ctx deps"
```

---

## Task 9 — Integration tests (migration + repository isolation)

**Files:**
- Create: `backend/tests/integration/test_users_tenants_migration.py`
- Create: `backend/tests/integration/test_repository_tenant_isolation.py`

- [ ] **Step 9.1: Create `test_users_tenants_migration.py`**

```python
import subprocess

import asyncio
import pytest
from sqlalchemy import inspect, text

from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings


@pytest.mark.integration
async def test_migration_0002_creates_tables(settings: Settings) -> None:
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
    factory = build_session_factory(engine)
    async with factory() as session:
        # alembic_version at 0002
        v = (await session.execute(
            text("SELECT version_num FROM alembic_version")
        )).scalar()
        assert v == "0002"
        # tables exist
        async with engine.connect() as conn:
            tables = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names()
            )
            assert "tenants" in tables
            assert "users" in tables
    await engine.dispose()
```

- [ ] **Step 9.2: Create `test_repository_tenant_isolation.py`**

```python
from uuid import uuid4

import pytest

from tfm_rag.domain.errors.common import NotFoundError, TenantScopeViolation
from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.persistence.models.tenants import TenantRow
from tfm_rag.infrastructure.persistence.repository import (
    BaseRepository,
    RequestContext,
)
from tfm_rag.infrastructure.settings import Settings


class TenantRepository(BaseRepository[TenantRow]):
    model = TenantRow


def _tenant(tenant_id) -> TenantRow:
    return TenantRow(
        id=tenant_id,
        name=f"t-{tenant_id}",
        qdrant_collection_prefix=f"kb_chunks__{tenant_id}",
        storage_prefix=f"tenant_{tenant_id}/",
    )


@pytest.mark.integration
async def test_tenant_a_cannot_see_tenant_b(settings: Settings) -> None:
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)

    tenant_a_id = uuid4()
    tenant_b_id = uuid4()
    ctx_a = RequestContext(tenant_id=tenant_a_id)
    ctx_b = RequestContext(tenant_id=tenant_b_id)

    # Tenant A creates its tenant row
    async with factory() as session:
        repo_a = TenantRepository(session, ctx_a)
        await repo_a.add(_tenant(tenant_a_id))
        await session.commit()

    # Tenant B creates its own
    async with factory() as session:
        repo_b = TenantRepository(session, ctx_b)
        await repo_b.add(_tenant(tenant_b_id))
        await session.commit()

    # Tenant B tries to read tenant A's row by id → NotFound
    async with factory() as session:
        repo_b_read = TenantRepository(session, ctx_b)
        with pytest.raises(NotFoundError):
            await repo_b_read.get(tenant_a_id)

    # Tenant B tries to add a row with tenant_id of A → TenantScopeViolation
    async with factory() as session:
        repo_b_add = TenantRepository(session, ctx_b)
        bad_row = _tenant(tenant_a_id)
        with pytest.raises(TenantScopeViolation):
            await repo_b_add.add(bad_row)

    await engine.dispose()
```

- [ ] **Step 9.3: Commit**

```bash
git add backend/tests/integration/test_users_tenants_migration.py \
        backend/tests/integration/test_repository_tenant_isolation.py
git commit -m "test(infra): migration 0002 + tenant isolation integration tests"
```

---

## Task 10 — Final verification + tag

**This task is run by the controller (humano + tooling), not a subagent.** After all commits land:

- [ ] **Step 10.1: Run lint, types, unit tests**

```bash
cd backend
source .venv/bin/activate
ruff check .
mypy src/
pytest tests/ -v -m "not integration"
```
All three should pass.

- [ ] **Step 10.2: (when Docker is available) Run integration tests**

```bash
cd ../infra
docker compose up -d postgres
cd ../backend
alembic upgrade head
pytest tests/integration -v -m integration
```
Expect all integration tests to pass.

- [ ] **Step 10.3: Tag**

```bash
git tag cap-02-infra-tenant-isolation
```

---

## Done criteria for CAP-INFRA-TENANT-ISOLATION

- Migration 0002 creates `tenants` and `users` tables per spec §9.
- `BaseRepository[E]` filters every query by `ctx.tenant_id` and refuses cross-tenant writes via `TenantScopeViolation`.
- JWT encode/decode helpers are implemented and tested.
- `TenantScopingMiddleware` extracts `tenant_id`/`user_id` from JWT, attaches `RequestContext` to `request.state.ctx`, returns 401 for missing/invalid tokens, lets unauthenticated paths through.
- `app.py` registers the middleware.
- All unit tests pass; integration tests pass when Docker is up.

## What plan #3 will build on top

`CAP-INFRA-SECRETS` (plan #3) adds:
- `FernetSecretEncryptor` adapter implementing a `SecretEncryptor` port.
- Used by `CAP-INTEG-CREDENTIALS` (plan #6) and `CAP-KB-DB-SOURCES` (plan #9) for cifrar/descifrar credenciales sensibles.
