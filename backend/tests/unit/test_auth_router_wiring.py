"""Wiring tests for /api/auth — Task 8 hexagonal migration.

The auth router used to pass the raw AsyncSession positionally into the use
cases; it now composes `UserRepository(session)` /
`TenantProvisioningRepository(session)` / `BcryptPasswordHasher()` and calls
them with keyword-only args. These tests patch each use case with a fake
that mirrors the REAL keyword-only signature exactly (so an old-style
`login_user(session, email=..., ...)` caller would raise TypeError — same
technique as Task 6's /search regression test) and assert the composed
dependency types plus the unchanged Set-Cookie behaviour.
"""
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from tfm_rag.application.auth.login_user import LoginUserResult
from tfm_rag.application.auth.login_with_google import LoginWithGoogleResult
from tfm_rag.application.auth.register_user import RegisterUserResult
from tfm_rag.domain.ports.oauth_verifier import OAuthVerifier
from tfm_rag.domain.ports.password_hasher import PasswordHasher
from tfm_rag.domain.ports.repositories import (
    TenantRepositoryPort,
    UserRepositoryPort,
)
from tfm_rag.infrastructure.api.app import create_app
from tfm_rag.infrastructure.api.auth_cookie import COOKIE_NAME
from tfm_rag.infrastructure.api.dependencies import get_session, get_settings
from tfm_rag.infrastructure.auth.password import BcryptPasswordHasher
from tfm_rag.infrastructure.persistence.repositories.tenants_repo import (
    TenantProvisioningRepository,
)
from tfm_rag.infrastructure.persistence.repositories.users_repo import (
    UserRepository,
)
from tfm_rag.infrastructure.settings import Settings

SECRET = "x" * 32
FERNET_KEY = "qjd374RRcCpzdVhmmLHCnjxvBfrFwbwErhxIj4nq_XM="

_USER_ID = uuid4()
_TENANT_ID = uuid4()
_EMAIL = "test@example.com"

_SENTINEL_SESSION = object()


def _make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = dict(
        postgres_url="postgresql+asyncpg://u:p@h:5432/d",
        qdrant_url="http://qdrant:6333",
        ollama_base_url="http://ollama:11434",
        jwt_secret=SECRET,
        fernet_key=FERNET_KEY,
        cookie_secure=False,
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _client(settings: Settings | None = None) -> TestClient:
    app = create_app()
    fake_settings = settings or _make_settings()

    async def _fake_session():
        yield _SENTINEL_SESSION

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_settings] = lambda: fake_settings
    return TestClient(app, raise_server_exceptions=True)


def test_login_composes_user_repo_and_password_hasher() -> None:
    captured: dict[str, object] = {}

    # Mirrors the REAL keyword-only signature: any positional/legacy-kw call
    # from the router would TypeError here.
    async def _fake_login_user(
        *,
        users_repo: UserRepositoryPort,
        password_hasher: PasswordHasher,
        email: str,
        password: str,
    ) -> LoginUserResult:
        captured.update(
            users_repo=users_repo, password_hasher=password_hasher,
            email=email, password=password,
        )
        return LoginUserResult(
            user_id=_USER_ID, tenant_id=_TENANT_ID, email=email
        )

    client = _client()
    with patch(
        "tfm_rag.infrastructure.api.routers.auth.login_user",
        new=_fake_login_user,
    ):
        resp = client.post(
            "/api/auth/login", json={"email": _EMAIL, "password": "password123"}
        )

    assert resp.status_code == 200, resp.text
    # Composition: real adapters, built from the request session.
    assert isinstance(captured["users_repo"], UserRepository)
    assert captured["users_repo"]._session is _SENTINEL_SESSION
    assert isinstance(captured["password_hasher"], BcryptPasswordHasher)
    assert captured["email"] == _EMAIL
    assert captured["password"] == "password123"
    # Cookie contract unchanged.
    set_cookie = resp.headers.get("set-cookie", "")
    assert COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie


def test_register_composes_user_and_tenant_repos() -> None:
    captured: dict[str, object] = {}

    async def _fake_register_user(
        *,
        users_repo: UserRepositoryPort,
        tenants_repo: TenantRepositoryPort,
        password_hasher: PasswordHasher,
        email: str,
        password: str,
    ) -> RegisterUserResult:
        captured.update(
            users_repo=users_repo, tenants_repo=tenants_repo,
            password_hasher=password_hasher,
        )
        return RegisterUserResult(
            user_id=_USER_ID, tenant_id=_TENANT_ID, email=email
        )

    client = _client()
    with patch(
        "tfm_rag.infrastructure.api.routers.auth.register_user",
        new=_fake_register_user,
    ):
        resp = client.post(
            "/api/auth/register",
            json={"email": _EMAIL, "password": "password123"},
        )

    assert resp.status_code == 201, resp.text
    assert isinstance(captured["users_repo"], UserRepository)
    assert isinstance(captured["tenants_repo"], TenantProvisioningRepository)
    assert captured["tenants_repo"]._session is _SENTINEL_SESSION
    assert isinstance(captured["password_hasher"], BcryptPasswordHasher)
    set_cookie = resp.headers.get("set-cookie", "")
    assert COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie


def test_login_google_composes_repos_and_verifier() -> None:
    captured: dict[str, object] = {}

    async def _fake_login_with_google(
        *,
        users_repo: UserRepositoryPort,
        tenants_repo: TenantRepositoryPort,
        verifier: OAuthVerifier,
        google_id_token: str,
    ) -> LoginWithGoogleResult:
        captured.update(
            users_repo=users_repo, tenants_repo=tenants_repo,
            verifier=verifier, google_id_token=google_id_token,
        )
        return LoginWithGoogleResult(
            user_id=_USER_ID, tenant_id=_TENANT_ID, email=_EMAIL
        )

    client = _client(_make_settings(google_oauth_client_id="test-client-id"))
    with patch(
        "tfm_rag.infrastructure.api.routers.auth.login_with_google",
        new=_fake_login_with_google,
    ):
        resp = client.post(
            "/api/auth/login/google", json={"google_id_token": "tok"}
        )

    assert resp.status_code == 200, resp.text
    assert isinstance(captured["users_repo"], UserRepository)
    assert isinstance(captured["tenants_repo"], TenantProvisioningRepository)
    assert captured["google_id_token"] == "tok"
    # Verifier built from settings.google_oauth_client_id
    from tfm_rag.infrastructure.auth.google_oauth import GoogleOAuthVerifier

    assert isinstance(captured["verifier"], GoogleOAuthVerifier)
    set_cookie = resp.headers.get("set-cookie", "")
    assert COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie
