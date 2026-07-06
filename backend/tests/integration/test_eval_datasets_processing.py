# backend/tests/integration/test_eval_datasets_processing.py
"""Integration test: upload SQL seed + process dataset → status 'ready'."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import tfm_rag.infrastructure.api.dependencies as _deps
from tfm_rag.infrastructure.api.app import app
from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings, get_settings

# ---------------------------------------------------------------------------
# Helpers shared with test_eval_datasets_endpoints.py (inlined to keep the
# two test modules independent; lift to conftest.py if a third module needs them).
# ---------------------------------------------------------------------------

async def _register(client: AsyncClient, email: str) -> tuple[str, str]:
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "correctpassword"},
    )
    assert r.status_code == 201, r.text
    # Eval routes require superadmin: grant it, then re-login so the returned
    # token carries the `sa` claim.
    _engine = build_engine(get_settings().postgres_url)
    _factory = build_session_factory(_engine)
    async with _factory() as _s:
        await _s.execute(
            text("UPDATE users SET is_superadmin = true WHERE email = :e"),
            {"e": email},
        )
        await _s.commit()
    await _engine.dispose()
    relogin = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "correctpassword"},
    )
    assert relogin.status_code == 200, relogin.text
    body = relogin.json()
    return body["access_token"], body["tenant_id"]


async def _ollama_credential_id(client: AsyncClient, token: str) -> str:
    r = await client.get(
        "/api/credentials",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    creds = r.json()
    ollama = next(c for c in creds if c["provider_id"] == "ollama")
    return ollama["id"]


# ---------------------------------------------------------------------------
# Fixture: fresh DB + authenticated ASGI client
# ---------------------------------------------------------------------------

@pytest.fixture
async def eval_client(settings: Settings):
    """Yields (client, auth_headers, embedding_selection_dict)."""
    _deps._session_factory = None
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    async with factory() as s:
        await s.execute(text(
            "TRUNCATE eval_dataset_rows, eval_datasets, sources, knowledge_bases, "
            "provider_credentials, users, tenants RESTART IDENTITY CASCADE"
        ))
        await s.commit()
    await engine.dispose()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, _tenant_id = await _register(client, "proc-ds-user@example.com")
        cred_id = await _ollama_credential_id(client, token)
        headers = {"Authorization": f"Bearer {token}"}
        embedding_selection = {
            "credential_id": cred_id,
            "model_id": "bge-m3",
            "dim": 1024,
        }
        yield client, headers, embedding_selection


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_upload_seed_and_process_marks_ready(eval_client) -> None:
    client, headers, embedding_selection = eval_client

    # 1. Create dataset
    create = await client.post(
        "/api/admin/eval/datasets",
        headers=headers,
        json={"name": "Proc DS", "embedding_selection": embedding_selection},
    )
    assert create.status_code == 201, create.text
    ds_id = create.json()["id"]

    # 2. Upload SQL seed
    seed = (
        "CREATE TABLE widgets (id INT PRIMARY KEY, name VARCHAR(50));\n"
        "INSERT INTO widgets VALUES (1,'a'),(2,'b');"
    )
    up = await client.post(
        f"/api/admin/eval/datasets/{ds_id}/sql-seed",
        headers=headers,
        json={"sql": seed},
    )
    assert up.status_code == 200, up.text

    # 3. Process dataset
    proc = await client.post(
        f"/api/admin/eval/datasets/{ds_id}/process",
        headers=headers,
    )
    assert proc.status_code == 200, proc.text
    body = proc.json()
    assert body["status"] == "ready", body
    assert body["db_schema_name"] is not None
    assert body["db_schema_name"].startswith("evalds_"), body

    # 4. Cleanup: delete the dataset (cascades the KB; eval DB is kept — deferred cleanup)
    deleted = await client.delete(
        f"/api/admin/eval/datasets/{ds_id}", headers=headers
    )
    assert deleted.status_code == 204, deleted.text
