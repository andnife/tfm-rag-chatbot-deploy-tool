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


@pytest.fixture
async def _clean_eval_tables(settings: Settings) -> None:
    # Reset the module-level session factory so each test gets a fresh
    # connection pool bound to its own event loop.
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


@pytest.mark.integration
async def test_create_list_import_delete_dataset(_clean_eval_tables: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, _tenant_id = await _register(client, "eval-ds-user@example.com")
        cred_id = await _ollama_credential_id(client, token)
        headers = {"Authorization": f"Bearer {token}"}

        embedding_selection = {
            "credential_id": cred_id,
            "model_id": "bge-m3",
            "dim": 1024,
        }

        # Create dataset
        create = await client.post(
            "/api/admin/eval/datasets",
            headers=headers,
            json={
                "name": "Suite QA",
                "description": "demo",
                "embedding_selection": embedding_selection,
            },
        )
        assert create.status_code == 201, create.text
        ds = create.json()
        assert ds["status"] == "draft"
        assert ds["knowledge_base_id"]
        ds_id = ds["id"]

        # List
        listed = await client.get("/api/admin/eval/datasets", headers=headers)
        assert listed.status_code == 200, listed.text
        assert any(d["id"] == ds_id for d in listed.json())

        # Get single
        got = await client.get(f"/api/admin/eval/datasets/{ds_id}", headers=headers)
        assert got.status_code == 200, got.text
        assert got.json()["id"] == ds_id

        # Import JSONL rows
        jsonl = (
            '{"question": "¿garantía?", "ground_truth": "3 años", '
            '"scenario": "doc_only", "complexity": "factual"}'
        )
        imp = await client.post(
            f"/api/admin/eval/datasets/{ds_id}/rows/import",
            headers=headers,
            json={"jsonl": jsonl},
        )
        assert imp.status_code == 200, imp.text
        assert imp.json()["num_rows"] == 1

        # List rows
        rows = await client.get(
            f"/api/admin/eval/datasets/{ds_id}/rows", headers=headers
        )
        assert rows.status_code == 200, rows.text
        assert rows.json()[0]["question"] == "¿garantía?"

        # Delete
        deleted = await client.delete(
            f"/api/admin/eval/datasets/{ds_id}", headers=headers
        )
        assert deleted.status_code == 204, deleted.text

        # 404 after delete
        missing = await client.get(
            f"/api/admin/eval/datasets/{ds_id}", headers=headers
        )
        assert missing.status_code == 404, missing.text


@pytest.mark.integration
async def test_invalid_row_operations_return_400(
    _clean_eval_tables: None,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, _tenant_id = await _register(client, "eval-ds-bad-rows@example.com")
        cred_id = await _ollama_credential_id(client, token)
        headers = {"Authorization": f"Bearer {token}"}

        embedding_selection = {
            "credential_id": cred_id,
            "model_id": "bge-m3",
            "dim": 1024,
        }

        # Create a dataset to operate on
        create = await client.post(
            "/api/admin/eval/datasets",
            headers=headers,
            json={
                "name": "Bad Rows Suite",
                "description": "negative test",
                "embedding_selection": embedding_selection,
            },
        )
        assert create.status_code == 201, create.text
        ds_id = create.json()["id"]

        # Malformed JSONL (not valid JSON) must return 400, not 500
        bad_jsonl = await client.post(
            f"/api/admin/eval/datasets/{ds_id}/rows/import",
            headers=headers,
            json={"jsonl": "{not json}"},
        )
        assert bad_jsonl.status_code == 400, bad_jsonl.text

        # PUT with a row that has empty ground_truth must return 400, not 500
        bad_row = await client.put(
            f"/api/admin/eval/datasets/{ds_id}/rows",
            headers=headers,
            json={
                "rows": [
                    {
                        "question": "¿garantía?",
                        "ground_truth": "",
                        "scenario": "doc_only",
                        "complexity": "factual",
                    }
                ]
            },
        )
        assert bad_row.status_code == 400, bad_row.text
