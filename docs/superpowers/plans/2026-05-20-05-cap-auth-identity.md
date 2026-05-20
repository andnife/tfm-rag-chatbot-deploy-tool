# CAP-AUTH-IDENTITY Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Implement registration, login (email+password and Google OAuth), and `BootstrapTenant` so that a new user can sign up, automatically gets a Tenant, and receives a JWT.

**Architecture:** Email + bcrypt for passwords. Google OAuth verifies `id_token` via `google-auth`. `BootstrapTenant` creates a `TenantRow`. (Ollama default `ProviderCredential` creation is deferred to plan #6 once `provider_credentials` table exists.) Auth endpoints live under `/api/auth/*` and are unauthenticated (already whitelisted in `TenantScopingMiddleware`).

**Tech Stack:** bcrypt, google-auth, FastAPI.

**Depends on:** Plan #1 (Settings, engine), Plan #2 (User/Tenant ORM, JWT helpers, middleware), Plan #3 (none directly — SecretEncryptor will be used in plan #6).

---

## File structure

```
backend/src/tfm_rag/
├── domain/
│   ├── errors/auth.py              # InvalidCredentialsError + already-exists
│   └── ports/oauth_verifier.py     # abstract OAuthVerifier
├── infrastructure/
│   ├── auth/
│   │   ├── password.py             # bcrypt hash + verify
│   │   └── google_oauth.py         # GoogleOAuthVerifier adapter
│   ├── persistence/
│   │   └── repositories/
│   │       ├── __init__.py
│   │       ├── tenants_repo.py     # TenantRepository (special-case)
│   │       └── users_repo.py       # UserRepository
│   └── api/
│       └── routers/auth.py         # /api/auth/* endpoints
└── application/
    ├── __init__.py
    └── auth/
        ├── __init__.py
        ├── bootstrap_tenant.py
        ├── register_user.py
        ├── login_user.py
        └── login_with_google.py

backend/tests/unit/
├── test_password.py
├── test_register_user.py
├── test_login_user.py
└── test_login_with_google.py

backend/tests/integration/
└── test_auth_endpoints.py
```

---

## Task 1 — Password hashing helper + auth errors

### Step 1.1: Add `bcrypt` to `backend/pyproject.toml`

Add to `dependencies` list:

```toml
    "bcrypt>=4.2",
```

### Step 1.2: Install deps

```bash
cd backend
source .venv/bin/activate
pip install -e ".[dev]"
```

### Step 1.3: Create `backend/src/tfm_rag/infrastructure/auth/password.py`

```python
import bcrypt


def hash_password(plain: str) -> str:
    """Return a bcrypt hash (cost 12) of `plain`."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True iff `plain` matches the bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False
```

### Step 1.4: Create `backend/src/tfm_rag/domain/errors/auth.py`

```python
from tfm_rag.domain.errors.common import DomainError


class InvalidCredentialsError(DomainError):
    """Raised when login credentials are wrong."""


class UserAlreadyExistsError(DomainError):
    """Raised when registering a user whose email or google_sub already exists."""
```

### Step 1.5: Create `backend/tests/unit/test_password.py`

```python
from tfm_rag.infrastructure.auth.password import hash_password, verify_password


def test_hash_verify_roundtrip() -> None:
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True
    assert verify_password("wrong", h) is False


def test_different_passwords_produce_different_hashes() -> None:
    h1 = hash_password("abc")
    h2 = hash_password("abc")
    assert h1 != h2  # bcrypt has random salt


def test_corrupted_hash_returns_false() -> None:
    assert verify_password("anything", "not-a-bcrypt-hash") is False
```

### Step 1.6: Commit

```bash
git add backend/pyproject.toml \
        backend/src/tfm_rag/infrastructure/auth/password.py \
        backend/src/tfm_rag/domain/errors/auth.py \
        backend/tests/unit/test_password.py
git commit -m "feat(auth): bcrypt password hashing + auth errors"
```

---

## Task 2 — User/Tenant repositories

### Step 2.1: Create `backend/src/tfm_rag/infrastructure/persistence/repositories/__init__.py` (empty)

### Step 2.2: Create `backend/src/tfm_rag/infrastructure/persistence/repositories/tenants_repo.py`

```python
from uuid import UUID

from sqlalchemy import select

from tfm_rag.domain.errors.common import (
    NotFoundError,
    TenantScopeViolationError,
)
from tfm_rag.infrastructure.persistence.models.tenants import TenantRow
from tfm_rag.infrastructure.persistence.repository import (
    BaseRepository,
    RequestContext,
)


class TenantRepository(BaseRepository[TenantRow]):
    """Repository for the tenants table.

    Special-cased because `tenants` has no `tenant_id` column — the row's own
    `id` IS the tenant.
    """
    model = TenantRow

    def _check_tenant(self, row: object) -> None:  # type: ignore[override]
        row_id = getattr(row, "id", None)
        if row_id != self._ctx.tenant_id:
            raise TenantScopeViolationError(
                f"TenantRow id {row_id} != context tenant {self._ctx.tenant_id}"
            )

    async def get(self, row_id: UUID) -> TenantRow:  # type: ignore[override]
        if row_id != self._ctx.tenant_id:
            raise NotFoundError(f"TenantRow({row_id}) not found in tenant")
        stmt = select(TenantRow).where(TenantRow.id == row_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"TenantRow({row_id}) not found in tenant")
        return row
```

### Step 2.3: Create `backend/src/tfm_rag/infrastructure/persistence/repositories/users_repo.py`

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.infrastructure.persistence.models.users import UserRow


class UsersByEmailFinder:
    """Email-based lookup is unauthenticated (used during login), so it
    bypasses the standard tenant-aware repository pattern.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_email(self, email: str) -> UserRow | None:
        stmt = select(UserRow).where(UserRow.email == email)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def find_by_google_sub(self, google_sub: str) -> UserRow | None:
        stmt = select(UserRow).where(UserRow.google_sub == google_sub)
        return (await self._session.execute(stmt)).scalar_one_or_none()
```

### Step 2.4: Commit

```bash
git add backend/src/tfm_rag/infrastructure/persistence/repositories/
git commit -m "feat(infra): TenantRepository + UsersByEmailFinder"
```

---

## Task 3 — `BootstrapTenant` + `RegisterUser` use cases

### Step 3.1: Create `backend/src/tfm_rag/application/__init__.py` (empty)

### Step 3.2: Create `backend/src/tfm_rag/application/auth/__init__.py` (empty)

### Step 3.3: Create `backend/src/tfm_rag/application/auth/bootstrap_tenant.py`

```python
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

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
    """Create a fresh Tenant row.

    NOTE: The default Ollama ProviderCredential is created in plan #6 (after
    CAP-INTEG-CREDENTIALS introduces the table).
    """
    tenant_id = uuid4()
    prefix = f"kb_chunks__{tenant_id}"
    storage = f"tenant_{tenant_id}/"
    row = TenantRow(
        id=tenant_id,
        name=name,
        qdrant_collection_prefix=prefix,
        storage_prefix=storage,
    )
    session.add(row)
    await session.flush()
    return BootstrapTenantResult(
        tenant_id=tenant_id,
        qdrant_collection_prefix=prefix,
        storage_prefix=storage,
    )
```

### Step 3.4: Create `backend/src/tfm_rag/application/auth/register_user.py`

```python
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.auth.bootstrap_tenant import bootstrap_tenant
from tfm_rag.domain.errors.auth import UserAlreadyExistsError
from tfm_rag.infrastructure.auth.password import hash_password
from tfm_rag.infrastructure.persistence.models.users import UserRow
from tfm_rag.infrastructure.persistence.repositories.users_repo import (
    UsersByEmailFinder,
)


@dataclass(frozen=True, slots=True)
class RegisterUserResult:
    user_id: UUID
    tenant_id: UUID
    email: str


async def register_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
) -> RegisterUserResult:
    finder = UsersByEmailFinder(session)
    if await finder.find_by_email(email) is not None:
        raise UserAlreadyExistsError(f"Email {email} already registered")

    bt = await bootstrap_tenant(session, name=email)

    user_id = uuid4()
    row = UserRow(
        id=user_id,
        email=email,
        password_hash=hash_password(password),
        google_sub=None,
        tenant_id=bt.tenant_id,
    )
    session.add(row)
    await session.flush()
    return RegisterUserResult(
        user_id=user_id, tenant_id=bt.tenant_id, email=email
    )
```

### Step 3.5: Create `backend/src/tfm_rag/application/auth/login_user.py`

```python
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.auth import InvalidCredentialsError
from tfm_rag.infrastructure.auth.password import verify_password
from tfm_rag.infrastructure.persistence.repositories.users_repo import (
    UsersByEmailFinder,
)


@dataclass(frozen=True, slots=True)
class LoginUserResult:
    user_id: UUID
    tenant_id: UUID
    email: str


async def login_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
) -> LoginUserResult:
    finder = UsersByEmailFinder(session)
    user = await finder.find_by_email(email)
    if user is None or user.password_hash is None:
        raise InvalidCredentialsError("Invalid email or password")
    if not verify_password(password, user.password_hash):
        raise InvalidCredentialsError("Invalid email or password")
    return LoginUserResult(
        user_id=user.id, tenant_id=user.tenant_id, email=user.email
    )
```

### Step 3.6: Commit

```bash
git add backend/src/tfm_rag/application/
git commit -m "feat(auth): BootstrapTenant + RegisterUser + LoginUser use cases"
```

---

## Task 4 — Google OAuth port + adapter + LoginWithGoogle

### Step 4.1: Create `backend/src/tfm_rag/domain/ports/oauth_verifier.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OAuthProfile:
    sub: str
    email: str
    email_verified: bool


class OAuthVerifier(ABC):
    @abstractmethod
    async def verify(self, id_token: str) -> OAuthProfile:
        """Verify the id_token signature + claims. Raises if invalid."""
```

### Step 4.2: Add `google-auth` to `backend/pyproject.toml`

Add to `dependencies`:

```toml
    "google-auth>=2.35",
```

### Step 4.3: Reinstall

```bash
cd backend
source .venv/bin/activate
pip install -e ".[dev]"
```

### Step 4.4: Create `backend/src/tfm_rag/infrastructure/auth/google_oauth.py`

```python
import asyncio
from typing import Any

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from tfm_rag.domain.errors.auth import InvalidCredentialsError
from tfm_rag.domain.ports.oauth_verifier import OAuthProfile, OAuthVerifier


class GoogleOAuthVerifier(OAuthVerifier):
    def __init__(self, client_id: str) -> None:
        self._client_id = client_id
        self._req = google_requests.Request()

    async def verify(self, id_token: str) -> OAuthProfile:
        try:
            info: dict[str, Any] = await asyncio.to_thread(
                google_id_token.verify_oauth2_token,
                id_token,
                self._req,
                self._client_id,
            )
        except ValueError as exc:
            raise InvalidCredentialsError(f"Invalid Google id_token: {exc}") from exc
        return OAuthProfile(
            sub=str(info["sub"]),
            email=str(info.get("email", "")),
            email_verified=bool(info.get("email_verified", False)),
        )
```

### Step 4.5: Create `backend/src/tfm_rag/application/auth/login_with_google.py`

```python
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.auth.bootstrap_tenant import bootstrap_tenant
from tfm_rag.domain.errors.auth import InvalidCredentialsError
from tfm_rag.domain.ports.oauth_verifier import OAuthVerifier
from tfm_rag.infrastructure.persistence.models.users import UserRow
from tfm_rag.infrastructure.persistence.repositories.users_repo import (
    UsersByEmailFinder,
)


@dataclass(frozen=True, slots=True)
class LoginWithGoogleResult:
    user_id: UUID
    tenant_id: UUID
    email: str


async def login_with_google(
    session: AsyncSession,
    verifier: OAuthVerifier,
    *,
    google_id_token: str,
) -> LoginWithGoogleResult:
    profile = await verifier.verify(google_id_token)
    if not profile.email_verified:
        raise InvalidCredentialsError("Google account email is not verified")

    finder = UsersByEmailFinder(session)
    user = await finder.find_by_google_sub(profile.sub)
    if user is None:
        # First-time login → create user + tenant
        bt = await bootstrap_tenant(session, name=profile.email)
        user_id = uuid4()
        new_user = UserRow(
            id=user_id,
            email=profile.email,
            password_hash=None,
            google_sub=profile.sub,
            tenant_id=bt.tenant_id,
        )
        session.add(new_user)
        await session.flush()
        return LoginWithGoogleResult(
            user_id=user_id, tenant_id=bt.tenant_id, email=profile.email
        )
    return LoginWithGoogleResult(
        user_id=user.id, tenant_id=user.tenant_id, email=user.email
    )
```

### Step 4.6: Commit

```bash
git add backend/pyproject.toml \
        backend/src/tfm_rag/domain/ports/oauth_verifier.py \
        backend/src/tfm_rag/infrastructure/auth/google_oauth.py \
        backend/src/tfm_rag/application/auth/login_with_google.py
git commit -m "feat(auth): Google OAuth verifier + LoginWithGoogle use case"
```

---

## Task 5 — API routers + integration test

### Step 5.1: Create `backend/src/tfm_rag/infrastructure/api/routers/auth.py`

```python
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.auth.login_user import login_user
from tfm_rag.application.auth.login_with_google import login_with_google
from tfm_rag.application.auth.register_user import register_user
from tfm_rag.domain.errors.auth import (
    InvalidCredentialsError,
    UserAlreadyExistsError,
)
from tfm_rag.infrastructure.api.dependencies import get_session
from tfm_rag.infrastructure.auth.google_oauth import GoogleOAuthVerifier
from tfm_rag.infrastructure.auth.jwt import encode_jwt
from tfm_rag.infrastructure.settings import Settings, get_settings


router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class GoogleLoginIn(BaseModel):
    google_id_token: str


class AuthOut(BaseModel):
    user_id: str
    tenant_id: str
    email: str
    token: str


def _token(*, user_id: Any, tenant_id: Any, settings: Settings) -> str:
    return encode_jwt(
        user_id=user_id,
        tenant_id=tenant_id,
        secret=settings.jwt_secret,
        expires_hours=settings.jwt_expires_hours,
    )


@router.post("/register", response_model=AuthOut, status_code=201)
async def register(
    body: RegisterIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AuthOut:
    try:
        result = await register_user(
            session, email=body.email, password=body.password
        )
    except UserAlreadyExistsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return AuthOut(
        user_id=str(result.user_id),
        tenant_id=str(result.tenant_id),
        email=result.email,
        token=_token(
            user_id=result.user_id, tenant_id=result.tenant_id, settings=settings
        ),
    )


@router.post("/login", response_model=AuthOut)
async def login(
    body: LoginIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AuthOut:
    try:
        result = await login_user(
            session, email=body.email, password=body.password
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    return AuthOut(
        user_id=str(result.user_id),
        tenant_id=str(result.tenant_id),
        email=result.email,
        token=_token(
            user_id=result.user_id, tenant_id=result.tenant_id, settings=settings
        ),
    )


@router.post("/login/google", response_model=AuthOut)
async def login_google(
    body: GoogleLoginIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AuthOut:
    if not settings.google_oauth_client_id:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth not configured",
        )
    verifier = GoogleOAuthVerifier(settings.google_oauth_client_id)
    try:
        result = await login_with_google(
            session, verifier, google_id_token=body.google_id_token
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    return AuthOut(
        user_id=str(result.user_id),
        tenant_id=str(result.tenant_id),
        email=result.email,
        token=_token(
            user_id=result.user_id, tenant_id=result.tenant_id, settings=settings
        ),
    )
```

### Step 5.2: Register the router in `backend/src/tfm_rag/infrastructure/api/app.py`

Replace the `create_app()` body to also include the auth router. Read the current file, then change:

```python
from tfm_rag.infrastructure.api.routers import health
```

to:

```python
from tfm_rag.infrastructure.api.routers import auth, health
```

And add inside `create_app()`:

```python
app.include_router(auth.router)
```

(below the existing `app.include_router(health.router)` line).

### Step 5.3: Create `backend/tests/integration/test_auth_endpoints.py`

```python
import pytest
from httpx import ASGITransport, AsyncClient

from tfm_rag.infrastructure.api.app import app


@pytest.mark.integration
async def test_register_then_login_then_me_flow() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register a fresh user
        reg = await client.post(
            "/api/auth/register",
            json={"email": "alice@example.com", "password": "correctpassword"},
        )
        assert reg.status_code == 201, reg.text
        reg_body = reg.json()
        assert reg_body["email"] == "alice@example.com"
        assert reg_body["token"]

        # Login with the same credentials
        login = await client.post(
            "/api/auth/login",
            json={"email": "alice@example.com", "password": "correctpassword"},
        )
        assert login.status_code == 200, login.text
        assert login.json()["user_id"] == reg_body["user_id"]

        # Wrong password
        bad = await client.post(
            "/api/auth/login",
            json={"email": "alice@example.com", "password": "wrong"},
        )
        assert bad.status_code == 401

        # Duplicate register
        dup = await client.post(
            "/api/auth/register",
            json={"email": "alice@example.com", "password": "x"},
        )
        assert dup.status_code == 409
```

### Step 5.4: Commit

```bash
git add backend/src/tfm_rag/infrastructure/api/routers/auth.py \
        backend/src/tfm_rag/infrastructure/api/app.py \
        backend/tests/integration/test_auth_endpoints.py
git commit -m "feat(auth): /api/auth/* routes (register, login, login/google) + integration test"
```

---

## Task 6 — Tag

```bash
git tag cap-05-auth-identity
```

---

## Done criteria

- `POST /api/auth/register` creates a new User + Tenant and returns JWT.
- `POST /api/auth/login` validates email+password and returns JWT.
- `POST /api/auth/login/google` validates Google id_token and returns JWT.
- Duplicate registration returns 409.
- Wrong password returns 401.
- All unit tests pass; integration test passes when Postgres is up.

## Deferred to plan #6

- BootstrapTenant also creates Ollama default `ProviderCredential` (depends on the `provider_credentials` table from plan #6).
