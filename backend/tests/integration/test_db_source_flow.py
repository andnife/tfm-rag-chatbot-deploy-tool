"""E2E for CAP-KB-DB-SOURCES: attach a real Postgres + MySQL DB as
DatabaseSource. Uses the live Docker stack:
  - tfm-rag-postgres-1 hosts a SECOND db `tfm_rag_source_test` for the app
    to introspect (separate from the app's own DB `tfm_rag`).
  - tfm-rag-mysql_source-1 hosts `tfm_rag_source_test`.

This test is `integration` — slow (~30s for both setup + introspection).
"""
import asyncio
from typing import Any

import asyncpg
import asyncmy
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import tfm_rag.infrastructure.api.dependencies as _deps
from tfm_rag.infrastructure.api.app import app
from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- helpers


async def _prepare_postgres_source_db() -> None:
    """Create `tfm_rag_source_test` inside the app's Postgres if missing,
    then ensure a `widgets` table exists with two columns."""
    admin = await asyncpg.connect(
        host="localhost", port=5432, user="tfm", password="tfm",
        database="tfm_rag",
    )
    try:
        exists = await admin.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            "tfm_rag_source_test",
        )
        if not exists:
            await admin.execute('CREATE DATABASE "tfm_rag_source_test"')
    finally:
        await admin.close()

    conn = await asyncpg.connect(
        host="localhost", port=5432, user="tfm", password="tfm",
        database="tfm_rag_source_test",
    )
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS widgets ("
            "id INTEGER PRIMARY KEY, name TEXT NOT NULL"
            ")"
        )
    finally:
        await conn.close()


async def _prepare_mysql_source_db() -> None:
    """Ensure a `widgets` table exists in MySQL `tfm_rag_source_test`."""
    conn = await asyncmy.connect(
        host="localhost", port=3306, user="tfm", password="tfm",
        db="tfm_rag_source_test",
    )
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                "CREATE TABLE IF NOT EXISTS widgets ("
                "id INT PRIMARY KEY, name VARCHAR(255) NOT NULL"
                ")"
            )
            await conn.commit()
    finally:
        conn.close()  # asyncmy close() is synchronous


@pytest.fixture
async def _clean_app_state(settings: Settings) -> None:
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


async def _register_and_create_kb(client: AsyncClient) -> tuple[str, str]:
    r = await client.post(
        "/api/auth/register",
        json={"email": "db-src-e2e@example.com", "password": "correctpassword"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    creds = (await client.get("/api/credentials", headers=h)).json()
    cred_id = next(c for c in creds if c["provider_id"] == "ollama")["id"]
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
    return token, r.json()["id"]


# --------------------------------------------------------------------------- tests


async def test_attach_postgres_database_source_e2e(
    _clean_app_state: None,
) -> None:
    await _prepare_postgres_source_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=60.0
    ) as c:
        token, kb_id = await _register_and_create_kb(c)
        h = {"Authorization": f"Bearer {token}"}

        # test-connection first
        r = await c.post(
            f"/api/knowledge-bases/{kb_id}/sources/test-connection",
            headers=h,
            json={
                "type": "database",
                "spec": {
                    "driver": "postgres",
                    "host": "localhost", "port": 5432,
                    "db_name": "tfm_rag_source_test",
                    "username": "tfm", "password": "tfm",
                    "ssl_mode": "disable",
                },
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

        # attach the database
        r = await c.post(
            f"/api/knowledge-bases/{kb_id}/sources/databases",
            headers=h,
            json={
                "driver": "postgres",
                "host": "localhost", "port": 5432,
                "db_name": "tfm_rag_source_test",
                "username": "tfm", "password": "tfm",
                "ssl_mode": "disable",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["snapshot_tables"] >= 1  # at least our `widgets`

        # verify the source shows up in the listing
        r = await c.get(
            f"/api/knowledge-bases/{kb_id}/sources", headers=h,
        )
        assert r.status_code == 200, r.text
        sources = r.json()
        db_sources = [s for s in sources if s["type"] == "database"]
        assert len(db_sources) == 1
        assert db_sources[0]["ingest_status"] == "done"


async def test_attach_mysql_database_source_e2e(
    _clean_app_state: None,
) -> None:
    await _prepare_mysql_source_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=60.0
    ) as c:
        token, kb_id = await _register_and_create_kb(c)
        h = {"Authorization": f"Bearer {token}"}

        # attach mysql
        r = await c.post(
            f"/api/knowledge-bases/{kb_id}/sources/databases",
            headers=h,
            json={
                "driver": "mysql",
                "host": "localhost", "port": 3306,
                "db_name": "tfm_rag_source_test",
                "username": "tfm", "password": "tfm",
                "ssl_mode": "disable",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["snapshot_tables"] >= 1


async def test_attach_with_wrong_password_returns_400(
    _clean_app_state: None,
) -> None:
    await _prepare_postgres_source_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=30.0
    ) as c:
        token, kb_id = await _register_and_create_kb(c)
        h = {"Authorization": f"Bearer {token}"}

        r = await c.post(
            f"/api/knowledge-bases/{kb_id}/sources/databases",
            headers=h,
            json={
                "driver": "postgres",
                "host": "localhost", "port": 5432,
                "db_name": "tfm_rag_source_test",
                "username": "tfm", "password": "WRONG",
                "ssl_mode": "disable",
            },
        )
        assert r.status_code == 400
        # Detail must NOT contain the bad password.
        assert "WRONG" not in r.json().get("detail", "")
