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


@pytest.fixture
async def _clean_kb_tables(settings: Settings) -> None:
    # Reset the module-level session factory so each test gets a fresh
    # connection pool bound to its own event loop.
    _deps._session_factory = None
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    async with factory() as s:
        await s.execute(text(
            "TRUNCATE sources, knowledge_bases, "
            "provider_credentials, users, tenants RESTART IDENTITY CASCADE"
        ))
        await s.commit()
    await engine.dispose()


async def _register(client: AsyncClient, email: str) -> tuple[str, str]:
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "correctpassword"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return body["token"], body["tenant_id"]


async def _ollama_credential_id(client: AsyncClient, token: str) -> str:
    r = await client.get(
        "/api/credentials",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    creds = r.json()
    ollama = next(c for c in creds if c["provider_id"] == "ollama")
    return ollama["id"]


@pytest.mark.integration
async def test_kb_full_lifecycle(_clean_kb_tables: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, tenant_id = await _register(client, "kb-user@example.com")
        cred_id = await _ollama_credential_id(client, token)
        h = {"Authorization": f"Bearer {token}"}

        # Create KB
        create = await client.post(
            "/api/knowledge-bases",
            headers=h,
            json={
                "name": "Manuals",
                "description": "User manuals",
                "embedding_selection": {
                    "provider_id": "ollama",
                    "credential_id": cred_id,
                    "model_id": "bge-m3",
                    "dim": 1024,
                },
            },
        )
        assert create.status_code == 201, create.text
        kb = create.json()
        kb_id = kb["id"]
        assert kb["name"] == "Manuals"
        assert kb["embedding_selection"]["dim"] == 1024

        # List
        listed = await client.get("/api/knowledge-bases", headers=h)
        assert listed.status_code == 200
        assert any(item["id"] == kb_id for item in listed.json())

        # Get with sources (empty)
        got = await client.get(f"/api/knowledge-bases/{kb_id}", headers=h)
        assert got.status_code == 200
        body = got.json()
        assert body["kb"]["id"] == kb_id
        assert body["sources"] == []

        # Patch name only — no reindex
        patched = await client.patch(
            f"/api/knowledge-bases/{kb_id}",
            headers=h,
            json={"name": "Manuals v2"},
        )
        assert patched.status_code == 200
        assert patched.json()["kb"]["name"] == "Manuals v2"
        assert patched.json()["reindex_required"] is False

        # Patch embedding dim — reindex required
        patched2 = await client.patch(
            f"/api/knowledge-bases/{kb_id}",
            headers=h,
            json={
                "embedding_selection": {
                    "provider_id": "ollama",
                    "credential_id": cred_id,
                    "model_id": "nomic-embed-text",
                    "dim": 768,
                }
            },
        )
        assert patched2.status_code == 200
        assert patched2.json()["reindex_required"] is True

        # Duplicate name rejected
        dup = await client.post(
            "/api/knowledge-bases",
            headers=h,
            json={
                "name": "Manuals v2",
                "embedding_selection": {
                    "provider_id": "ollama",
                    "credential_id": cred_id,
                    "model_id": "bge-m3",
                    "dim": 1024,
                },
            },
        )
        assert dup.status_code == 400

        # List sources (empty)
        srcs = await client.get(
            f"/api/knowledge-bases/{kb_id}/sources", headers=h
        )
        assert srcs.status_code == 200
        assert srcs.json() == []

        # Test-connection — database tester is registered; incomplete spec
        # returns ok=False (no host provided, connection attempt fails).
        tc = await client.post(
            f"/api/knowledge-bases/{kb_id}/sources/test-connection",
            headers=h,
            json={"type": "database", "spec": {"driver": "postgres"}},
        )
        assert tc.status_code == 200
        assert tc.json()["ok"] is False

        # Delete KB
        deleted = await client.delete(
            f"/api/knowledge-bases/{kb_id}", headers=h
        )
        assert deleted.status_code == 204

        # 404 after delete
        missing = await client.get(f"/api/knowledge-bases/{kb_id}", headers=h)
        assert missing.status_code == 404


@pytest.mark.integration
async def test_kb_isolation_between_tenants(_clean_kb_tables: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        alice_token, _ = await _register(client, "alice-kb@example.com")
        bob_token, _ = await _register(client, "bob-kb@example.com")
        alice_cred = await _ollama_credential_id(client, alice_token)

        # Alice creates a KB
        r = await client.post(
            "/api/knowledge-bases",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={
                "name": "Alice KB",
                "embedding_selection": {
                    "provider_id": "ollama",
                    "credential_id": alice_cred,
                    "model_id": "bge-m3",
                    "dim": 1024,
                },
            },
        )
        assert r.status_code == 201
        kb_id = r.json()["id"]

        # Bob cannot see it
        bob_list = await client.get(
            "/api/knowledge-bases",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert bob_list.status_code == 200
        assert bob_list.json() == []

        # Bob cannot fetch by id
        bob_get = await client.get(
            f"/api/knowledge-bases/{kb_id}",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert bob_get.status_code == 404
