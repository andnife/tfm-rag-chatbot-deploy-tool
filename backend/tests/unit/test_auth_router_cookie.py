"""Unit tests for Task 1.4: login/register set the httpOnly cookie,
POST /api/auth/logout clears it, and GET /api/auth/me reads from cookie.

We override `get_session` and `get_settings` dependencies and patch the
application-layer use case functions so no database is required.
"""
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from tfm_rag.application.auth.login_user import LoginUserResult
from tfm_rag.application.auth.register_user import RegisterUserResult
from tfm_rag.infrastructure.api.app import create_app
from tfm_rag.infrastructure.api.auth_cookie import COOKIE_NAME
from tfm_rag.infrastructure.api.dependencies import get_session, get_settings
from tfm_rag.infrastructure.auth.jwt import encode_jwt
from tfm_rag.infrastructure.settings import Settings

SECRET = "x" * 32
FERNET_KEY = "qjd374RRcCpzdVhmmLHCnjxvBfrFwbwErhxIj4nq_XM="

_FAKE_USER_ID = uuid4()
_FAKE_TENANT_ID = uuid4()
_FAKE_EMAIL = "test@example.com"


def _make_settings() -> Settings:
    """Build a Settings instance without real infrastructure URLs."""
    import os

    os.environ.setdefault(
        "POSTGRES_URL", "postgresql+asyncpg://u:p@h:5432/d"
    )
    os.environ.setdefault("QDRANT_URL", "http://qdrant:6333")
    os.environ.setdefault("OLLAMA_BASE_URL", "http://ollama:11434")
    os.environ.setdefault("JWT_SECRET", SECRET)
    os.environ.setdefault("FERNET_KEY", FERNET_KEY)
    return Settings(  # type: ignore[call-arg]
        postgres_url="postgresql+asyncpg://u:p@h:5432/d",
        qdrant_url="http://qdrant:6333",
        ollama_base_url="http://ollama:11434",
        jwt_secret=SECRET,
        fernet_key=FERNET_KEY,
        cookie_secure=False,
    )


def _client_with_mocked_deps() -> TestClient:
    app = create_app()

    fake_settings = _make_settings()

    async def _fake_session():
        # Yield a dummy — the use cases are patched so session is never used.
        yield object()

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_settings] = lambda: fake_settings

    return TestClient(app, raise_server_exceptions=True)


# ────────────────────────────────────────────────────────────────────────────
# login
# ────────────────────────────────────────────────────────────────────────────

def test_login_sets_httponly_cookie() -> None:
    """POST /api/auth/login must return a set-cookie header with tfm_rag_token
    and the HttpOnly flag."""
    login_result = LoginUserResult(
        user_id=_FAKE_USER_ID,
        tenant_id=_FAKE_TENANT_ID,
        email=_FAKE_EMAIL,
    )
    client = _client_with_mocked_deps()

    with patch(
        "tfm_rag.infrastructure.api.routers.auth.login_user",
        new=AsyncMock(return_value=login_result),
    ):
        resp = client.post(
            "/api/auth/login",
            json={"email": _FAKE_EMAIL, "password": "password123"},
        )

    assert resp.status_code == 200, resp.text
    set_cookie = resp.headers.get("set-cookie", "")
    assert COOKIE_NAME in set_cookie, f"Cookie not found in: {set_cookie}"
    assert "HttpOnly" in set_cookie, f"HttpOnly missing in: {set_cookie}"


# ────────────────────────────────────────────────────────────────────────────
# logout
# ────────────────────────────────────────────────────────────────────────────

def test_logout_returns_204_and_clears_cookie() -> None:
    """POST /api/auth/logout must return 204 with a Max-Age=0 set-cookie."""
    client = _client_with_mocked_deps()

    resp = client.post("/api/auth/logout")

    assert resp.status_code == 204, resp.text
    set_cookie = resp.headers.get("set-cookie", "")
    assert COOKIE_NAME in set_cookie, f"Cookie not found in: {set_cookie}"
    assert "Max-Age=0" in set_cookie, f"Max-Age=0 missing in: {set_cookie}"


# ────────────────────────────────────────────────────────────────────────────
# register
# ────────────────────────────────────────────────────────────────────────────

def test_register_sets_httponly_cookie() -> None:
    """POST /api/auth/register must also set the httpOnly cookie."""
    register_result = RegisterUserResult(
        user_id=_FAKE_USER_ID,
        tenant_id=_FAKE_TENANT_ID,
        email=_FAKE_EMAIL,
    )
    client = _client_with_mocked_deps()

    with patch(
        "tfm_rag.infrastructure.api.routers.auth.register_user",
        new=AsyncMock(return_value=register_result),
    ):
        resp = client.post(
            "/api/auth/register",
            json={"email": _FAKE_EMAIL, "password": "password123"},
        )

    assert resp.status_code == 201, resp.text
    set_cookie = resp.headers.get("set-cookie", "")
    assert COOKIE_NAME in set_cookie, f"Cookie not found in: {set_cookie}"
    assert "HttpOnly" in set_cookie, f"HttpOnly missing in: {set_cookie}"


# ────────────────────────────────────────────────────────────────────────────
# /me — cookie auth
# ────────────────────────────────────────────────────────────────────────────

def test_me_accepts_cookie() -> None:
    """GET /api/auth/me must accept a valid JWT in the cookie."""
    @dataclass
    class _FakeUser:
        id: UUID = _FAKE_USER_ID
        email: str = _FAKE_EMAIL
        tenant_id: UUID = _FAKE_TENANT_ID
        is_superadmin: bool = False

    token = encode_jwt(
        user_id=_FAKE_USER_ID,
        tenant_id=_FAKE_TENANT_ID,
        secret=SECRET,
        expires_hours=1,
    )

    app = create_app()
    fake_settings = _make_settings()
    app.dependency_overrides[get_settings] = lambda: fake_settings

    # Build a session mock whose execute(...).scalar_one_or_none() returns the
    # fake user, so get_me resolves without a real database.
    from unittest.mock import MagicMock

    fake_user = _FakeUser()
    mock_scalar = MagicMock()
    mock_scalar.scalar_one_or_none.return_value = fake_user
    mock_execute = AsyncMock(return_value=mock_scalar)
    mock_session = MagicMock()
    mock_session.execute = mock_execute

    async def _fake_session_with_mock():
        yield mock_session

    app.dependency_overrides[get_session] = _fake_session_with_mock

    client = TestClient(app, raise_server_exceptions=True)
    # Use the client's cookie jar to set the auth cookie
    client.cookies.set(COOKIE_NAME, token)
    resp = client.get("/api/auth/me")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(_FAKE_USER_ID)
    assert body["email"] == _FAKE_EMAIL


def test_me_returns_401_without_credentials() -> None:
    """GET /api/auth/me must return 401 when no cookie and no header."""
    client = _client_with_mocked_deps()
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401, resp.text
