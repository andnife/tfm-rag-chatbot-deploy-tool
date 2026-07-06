"""Tests that TenantScopingMiddleware accepts a JWT in the httpOnly cookie
and correctly rejects requests where neither cookie nor header is present.
"""
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from tfm_rag.infrastructure.api.auth_cookie import COOKIE_NAME
from tfm_rag.infrastructure.api.middleware.tenant_scoping import (
    TenantScopingMiddleware,
)
from tfm_rag.infrastructure.auth.jwt import encode_jwt
from tfm_rag.infrastructure.settings import Settings

SECRET = "x" * 32


@pytest.fixture
def jwt_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://u:p@h:5432/d")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setenv("FERNET_KEY", "qjd374RRcCpzdVhmmLHCnjxvBfrFwbwErhxIj4nq_XM=")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    return Settings()  # type: ignore[call-arg]


def _build_app(settings: Settings) -> FastAPI:
    app = FastAPI()
    app.add_middleware(TenantScopingMiddleware, settings=settings)

    @app.get("/api/protected")
    async def protected(request: Request) -> dict:
        return {"ok": True}

    return app


def test_cookie_auth_accepted(jwt_settings: Settings) -> None:
    """A valid JWT in the cookie must be accepted on a protected route (200)."""
    token = encode_jwt(
        user_id=uuid4(),
        tenant_id=uuid4(),
        secret=SECRET,
        expires_hours=1,
    )
    app = _build_app(jwt_settings)
    client = TestClient(app, raise_server_exceptions=True)
    client.cookies.set(COOKIE_NAME, token)
    resp = client.get("/api/protected")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}


def test_no_credentials_returns_401(jwt_settings: Settings) -> None:
    """No cookie and no Authorization header must return 401."""
    app = _build_app(jwt_settings)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/api/protected")
    assert resp.status_code == 401
