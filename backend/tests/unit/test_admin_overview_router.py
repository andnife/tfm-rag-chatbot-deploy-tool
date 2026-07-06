"""Wiring tests for /api/admin/overview — Task 8 hexagonal migration.

`admin_overview.py` used to build its response by querying 5 ORM models
directly with a raw AsyncSession. It now composes `AdminOverviewReader`
(implementing `AdminOverviewReaderPort`) from the request session and shapes
its domain dataclasses into the same JSON contract as before. These tests
prove the router still (a) requires superadmin, (b) constructs the reader
from the request session, and (c) reproduces the exact JSON shape.
"""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from tfm_rag.domain.entities.admin_overview import (
    ChatbotSummary,
    CredentialSummary,
    KnowledgeBaseSummary,
    TenantDetail,
    TenantOverview,
    TenantUserSummary,
)
from tfm_rag.infrastructure.api.app import create_app
from tfm_rag.infrastructure.api.auth_cookie import COOKIE_NAME
from tfm_rag.infrastructure.api.dependencies import get_session, get_settings
from tfm_rag.infrastructure.auth.jwt import encode_jwt
from tfm_rag.infrastructure.settings import Settings

SECRET = "x" * 32
FERNET_KEY = "qjd374RRcCpzdVhmmLHCnjxvBfrFwbwErhxIj4nq_XM="


def _make_settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        postgres_url="postgresql+asyncpg://u:p@h:5432/d",
        qdrant_url="http://qdrant:6333",
        ollama_base_url="http://ollama:11434",
        jwt_secret=SECRET,
        fernet_key=FERNET_KEY,
        cookie_secure=False,
    )


def _client(*, fake_session: object = object()) -> TestClient:
    app = create_app()
    fake_settings = _make_settings()

    async def _fake_session():
        yield fake_session

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_settings] = lambda: fake_settings
    return TestClient(app, raise_server_exceptions=True)


def _token(*, is_superadmin: bool) -> str:
    return encode_jwt(
        user_id=uuid4(), tenant_id=uuid4(), secret=SECRET,
        expires_hours=1, is_superadmin=is_superadmin,
    )


def test_list_tenants_requires_superadmin() -> None:
    client = _client()
    client.cookies.set(COOKIE_NAME, _token(is_superadmin=False))

    resp = client.get("/api/admin/overview/tenants")

    assert resp.status_code == 403


def test_list_tenants_without_auth_returns_401() -> None:
    client = _client()
    resp = client.get("/api/admin/overview/tenants")
    assert resp.status_code == 401


def test_list_tenants_composes_reader_from_session_and_shapes_json() -> None:
    """Proves the router builds `AdminOverviewReader(session)` (the real
    request session, not a global) and maps TenantOverview -> the legacy
    dict JSON shape exactly."""
    sentinel_session = object()
    client = _client(fake_session=sentinel_session)
    client.cookies.set(COOKIE_NAME, _token(is_superadmin=True))

    tenant_id = uuid4()
    user_id = uuid4()
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    fake_overview = [
        TenantOverview(
            tenant_id=tenant_id,
            name="Acme",
            users=[
                TenantUserSummary(
                    id=user_id, email="a@acme.com",
                    is_superadmin=False, created_at=created_at,
                )
            ],
        )
    ]

    captured_sessions: list[object] = []

    class _FakeReader:
        def __init__(self, session: object) -> None:
            captured_sessions.append(session)

        async def list_tenants_with_users(self):  # type: ignore[no-untyped-def]
            return fake_overview

    with patch(
        "tfm_rag.infrastructure.api.routers.admin_overview.AdminOverviewReader",
        new=_FakeReader,
    ):
        resp = client.get("/api/admin/overview/tenants")

    assert resp.status_code == 200, resp.text
    assert captured_sessions == [sentinel_session]
    assert resp.json() == [
        {
            "tenant_id": str(tenant_id),
            "name": "Acme",
            "users": [
                {
                    "id": str(user_id),
                    "email": "a@acme.com",
                    "is_superadmin": False,
                    "created_at": created_at.isoformat(),
                }
            ],
        }
    ]


def test_tenant_detail_composes_reader_and_shapes_json() -> None:
    sentinel_session = object()
    client = _client(fake_session=sentinel_session)
    client.cookies.set(COOKIE_NAME, _token(is_superadmin=True))

    tenant_id = uuid4()
    chatbot_id, kb_id, cred_id = uuid4(), uuid4(), uuid4()
    fake_detail = TenantDetail(
        tenant_id=tenant_id,
        chatbots=[ChatbotSummary(id=chatbot_id, name="Bot", description="d")],
        knowledge_bases=[KnowledgeBaseSummary(id=kb_id, name="KB", description=None)],
        credentials=[
            CredentialSummary(
                id=cred_id, provider_id="openai", label="default",
                base_url=None, config_source="TENANT_CREDENTIAL",
            )
        ],
    )

    reader_mock = AsyncMock()
    reader_mock.tenant_detail = AsyncMock(return_value=fake_detail)

    with patch(
        "tfm_rag.infrastructure.api.routers.admin_overview.AdminOverviewReader",
        return_value=reader_mock,
    ) as reader_cls:
        resp = client.get(f"/api/admin/overview/tenants/{tenant_id}")

    assert resp.status_code == 200, resp.text
    reader_cls.assert_called_once_with(sentinel_session)
    reader_mock.tenant_detail.assert_awaited_once_with(tenant_id)
    assert resp.json() == {
        "tenant_id": str(tenant_id),
        "chatbots": [{"id": str(chatbot_id), "name": "Bot", "description": "d"}],
        "knowledge_bases": [{"id": str(kb_id), "name": "KB", "description": None}],
        "credentials": [
            {
                "id": str(cred_id),
                "provider_id": "openai",
                "label": "default",
                "base_url": None,
                "config_source": "TENANT_CREDENTIAL",
            }
        ],
    }


def test_tenant_detail_requires_superadmin() -> None:
    client = _client()
    client.cookies.set(COOKIE_NAME, _token(is_superadmin=False))

    resp = client.get(f"/api/admin/overview/tenants/{uuid4()}")

    assert resp.status_code == 403
