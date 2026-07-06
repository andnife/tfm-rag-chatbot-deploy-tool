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
        "FERNET_KEY", "qjd374RRcCpzdVhmmLHCnjxvBfrFwbwErhxIj4nq_XM="
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
