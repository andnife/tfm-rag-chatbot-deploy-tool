"""Task 4 (T14): `POST /api/incidents` (frontend ErrorBoundary reports) must
require an authenticated user and attach the reporting tenant; `GET
/api/incidents` must require superadmin. Before this, the router existed
but was never mounted on the app (silent 404), so the frontend's error
reports were dropped and the endpoint effectively didn't exist.
"""
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tfm_rag.infrastructure.api import error_handler as error_handler_module
from tfm_rag.infrastructure.api.auth_cookie import COOKIE_NAME
from tfm_rag.infrastructure.api.middleware.tenant_scoping import (
    TenantScopingMiddleware,
)
from tfm_rag.infrastructure.api.routers import incidents
from tfm_rag.infrastructure.auth.jwt import encode_jwt
from tfm_rag.infrastructure.settings import Settings

SECRET = "x" * 32


@pytest.fixture(autouse=True)
def _clear_incidents() -> None:
    error_handler_module._incidents.clear()


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
    app.include_router(incidents.router)
    return app


def _token(*, tenant_id, user_id, is_superadmin: bool) -> str:
    return encode_jwt(
        user_id=user_id, tenant_id=tenant_id, secret=SECRET,
        expires_hours=1, is_superadmin=is_superadmin,
    )


_INCIDENT_BODY = {
    "status_code": 500,
    "error_code": "FRONTEND_ERROR",
    "message": "TypeError: cannot read properties of undefined",
    "detail": {"stack": "at Foo (bar.js:1:1)", "path": "/chatbots/123"},
}


# --- POST -----------------------------------------------------------------


def test_post_incident_without_auth_returns_401(jwt_settings: Settings) -> None:
    app = _build_app(jwt_settings)
    client = TestClient(app, raise_server_exceptions=True)

    resp = client.post("/api/incidents", json=_INCIDENT_BODY)

    assert resp.status_code == 401


def test_post_incident_with_auth_records_and_attaches_tenant(
    jwt_settings: Settings,
) -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    token = _token(tenant_id=tenant_id, user_id=user_id, is_superadmin=False)
    app = _build_app(jwt_settings)
    client = TestClient(app, raise_server_exceptions=True)
    client.cookies.set(COOKIE_NAME, token)

    resp = client.post("/api/incidents", json=_INCIDENT_BODY)

    assert resp.status_code in (200, 201), resp.text
    recorded = error_handler_module.get_incidents(limit=10)
    assert len(recorded) == 1
    assert recorded[0]["message"] == _INCIDENT_BODY["message"]
    assert recorded[0]["tenant_id"] == str(tenant_id)


def test_post_incident_does_not_require_superadmin(jwt_settings: Settings) -> None:
    """A regular (non-superadmin) authenticated user can report incidents —
    this is what the frontend ErrorBoundary does for any logged-in user."""
    token = _token(tenant_id=uuid4(), user_id=uuid4(), is_superadmin=False)
    app = _build_app(jwt_settings)
    client = TestClient(app, raise_server_exceptions=True)
    client.cookies.set(COOKIE_NAME, token)

    resp = client.post("/api/incidents", json=_INCIDENT_BODY)

    assert resp.status_code in (200, 201), resp.text


# --- GET --------------------------------------------------------------------


def test_get_incidents_without_auth_returns_401(jwt_settings: Settings) -> None:
    app = _build_app(jwt_settings)
    client = TestClient(app, raise_server_exceptions=True)

    resp = client.get("/api/incidents")

    assert resp.status_code == 401


def test_get_incidents_as_non_superadmin_returns_403(jwt_settings: Settings) -> None:
    token = _token(tenant_id=uuid4(), user_id=uuid4(), is_superadmin=False)
    app = _build_app(jwt_settings)
    client = TestClient(app, raise_server_exceptions=True)
    client.cookies.set(COOKIE_NAME, token)

    resp = client.get("/api/incidents")

    assert resp.status_code == 403


def test_get_incidents_as_superadmin_returns_recorded_incidents(
    jwt_settings: Settings,
) -> None:
    error_handler_module._record_incident(
        status_code=500, error_code="X", message="boom", detail=None,
        path="/x", method="GET", tb_str="",
    )
    token = _token(tenant_id=uuid4(), user_id=uuid4(), is_superadmin=True)
    app = _build_app(jwt_settings)
    client = TestClient(app, raise_server_exceptions=True)
    client.cookies.set(COOKIE_NAME, token)

    resp = client.get("/api/incidents")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["message"] == "boom"


# --- mounted on the real app -------------------------------------------------


def test_incidents_router_is_mounted_on_the_app() -> None:
    """Before this task the router existed but was never `include_router`-ed
    on `create_app()`, so the frontend's POST silently 404'd. A 401 (from
    the auth middleware) proves the route exists; a 404 would mean it's
    still unmounted.
    """
    from tfm_rag.infrastructure.api.app import create_app

    app = create_app()
    client = TestClient(app, raise_server_exceptions=True)

    resp = client.get("/api/incidents")

    assert resp.status_code == 401, resp.text
