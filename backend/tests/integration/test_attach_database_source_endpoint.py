"""Endpoint test: POST /api/knowledge-bases/{kb_id}/sources/databases.

This test is marked `integration` because it needs the live Postgres
container to host the application DB. The DatabaseConnector is REPLACED
with a fake via the SOURCE_CONNECTION_TESTERS registry monkey-patch so
no external DB is touched — only the app DB.
"""
import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

import tfm_rag.infrastructure.api.dependencies as _deps
from tfm_rag.infrastructure.api.app import app
from tfm_rag.infrastructure.database_connectors.source_tester import (
    DATABASE_CONNECTORS,
)
from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings
from sqlalchemy import text

pytestmark = pytest.mark.integration


class _FakeConnector:
    """Stand-in for PostgresConnector/MySQLConnector that records calls."""

    def __init__(self, *, fail_test: bool = False) -> None:
        self.fail_test = fail_test
        self.test_calls: list[dict[str, Any]] = []
        self.introspect_calls: list[dict[str, Any]] = []

    async def test_connection(self, spec: dict[str, Any]) -> None:
        self.test_calls.append(spec)
        if self.fail_test:
            from tfm_rag.domain.errors.knowledge import (
                DatabaseConnectionError,
            )
            raise DatabaseConnectionError("auth failed (fake)")

    async def introspect_schema(self, spec: dict[str, Any]) -> Any:
        from tfm_rag.domain.value_objects.database_schema import (
            ColumnSchema, DatabaseSchemaSnapshot, TableSchema,
        )
        self.introspect_calls.append(spec)
        return DatabaseSchemaSnapshot(
            captured_at=datetime(2026, 5, 25, 10, 0, tzinfo=timezone.utc),
            tables=(
                TableSchema(
                    schema="public", name="users",
                    columns=(
                        ColumnSchema(name="id", data_type="integer", nullable=False),
                        ColumnSchema(name="email", data_type="text", nullable=False),
                    ),
                ),
            ),
        )


@pytest.fixture(autouse=True)
async def _swap_postgres_connector() -> None:
    """Replace the production postgres connector with a fake for the test."""
    original = DATABASE_CONNECTORS["postgres"]
    DATABASE_CONNECTORS["postgres"] = _FakeConnector()  # type: ignore[assignment]
    yield
    DATABASE_CONNECTORS["postgres"] = original


@pytest.fixture
async def _clean_db(settings: Settings) -> None:
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    async with factory() as s:
        await s.execute(text(
            "TRUNCATE sources, knowledge_bases, provider_credentials, "
            "users, tenants RESTART IDENTITY CASCADE"
        ))
        await s.commit()
    await engine.dispose()
    _deps._session_factory = None


async def _register_and_get_cred(client: AsyncClient) -> tuple[str, str]:
    r = await client.post(
        "/api/auth/register",
        json={"email": "db-source@example.com", "password": "correctpassword"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    creds = (await client.get("/api/credentials", headers=h)).json()
    cred_id = next(c for c in creds if c["provider_id"] == "ollama")["id"]
    return token, cred_id


async def _create_kb(client: AsyncClient, token: str, cred_id: str) -> str:
    h = {"Authorization": f"Bearer {token}"}
    r = await client.post(
        "/api/knowledge-bases", headers=h,
        json={
            "name": "DBKB",
            "embedding_selection": {
                "provider_id": "ollama", "credential_id": cred_id,
                "model_id": "bge-m3", "dim": 1024,
            },
            "chunking_config": {
                "strategy": "fixed", "chunk_size": 300, "chunk_overlap": 50,
            },
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_attach_postgres_database_source_succeeds(
    _clean_db: None,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token, cred_id = await _register_and_get_cred(c)
        kb_id = await _create_kb(c, token, cred_id)
        h = {"Authorization": f"Bearer {token}"}

        r = await c.post(
            f"/api/knowledge-bases/{kb_id}/sources/databases",
            headers=h,
            json={
                "driver": "postgres",
                "host": "db.internal", "port": 5432, "db_name": "analytics",
                "username": "ro", "password": "secret",
                "ssl_mode": "disable",
            },
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert "source_id" in body
    assert body["snapshot_tables"] == 1
    assert "snapshot_captured_at" in body


async def test_attach_with_unknown_driver_returns_400(_clean_db: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token, cred_id = await _register_and_get_cred(c)
        kb_id = await _create_kb(c, token, cred_id)
        h = {"Authorization": f"Bearer {token}"}

        r = await c.post(
            f"/api/knowledge-bases/{kb_id}/sources/databases",
            headers=h,
            json={
                "driver": "oracle",  # rejected by Pydantic Literal validation
                "host": "h", "port": 5432, "db_name": "d",
                "username": "u", "password": "p",
            },
        )
    assert r.status_code == 422


async def test_attach_with_connection_failure_returns_400(
    _clean_db: None,
) -> None:
    DATABASE_CONNECTORS["postgres"] = _FakeConnector(fail_test=True)  # type: ignore[assignment]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token, cred_id = await _register_and_get_cred(c)
        kb_id = await _create_kb(c, token, cred_id)
        h = {"Authorization": f"Bearer {token}"}

        r = await c.post(
            f"/api/knowledge-bases/{kb_id}/sources/databases",
            headers=h,
            json={
                "driver": "postgres",
                "host": "h", "port": 5432, "db_name": "d",
                "username": "u", "password": "p",
            },
        )
    assert r.status_code == 400
    assert "auth failed" in r.json()["detail"].lower()


async def test_attach_with_missing_kb_returns_404(_clean_db: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token, _cred = await _register_and_get_cred(c)
        h = {"Authorization": f"Bearer {token}"}
        r = await c.post(
            f"/api/knowledge-bases/{uuid4()}/sources/databases",
            headers=h,
            json={
                "driver": "postgres",
                "host": "h", "port": 5432, "db_name": "d",
                "username": "u", "password": "p",
            },
        )
    assert r.status_code == 404
