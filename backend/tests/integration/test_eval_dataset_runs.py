"""Integration test for entity-dataset run and calibration endpoints.

POST /api/admin/eval/datasets/{dataset_id}/runs
POST /api/admin/eval/datasets/{dataset_id}/calibrate

Requires the full live Docker stack:
  postgres + qdrant + ollama (llama3.1 + bge-m3 + gemma3:1b)
"""
import asyncio

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

pytestmark = pytest.mark.integration


@pytest.fixture
async def _clean_eval_tables(settings: Settings) -> None:
    _deps._session_factory = None
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    async with factory() as s:
        await s.execute(text(
            "TRUNCATE eval_runs, eval_dataset_rows, eval_datasets, "
            "chat_messages, chat_sessions, chatbot_knowledge_base, chatbots, "
            "ingestion_jobs, sources, knowledge_bases, "
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


async def _ingest_doc(
    client: AsyncClient, token: str, kb_id: str, body: bytes
) -> None:
    h = {"Authorization": f"Bearer {token}"}
    upload = await client.post(
        f"/api/knowledge-bases/{kb_id}/sources/documents",
        headers=h,
        files={"file": ("manual.txt", body, "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    job_id = upload.json()["job_id"]
    for _ in range(120):
        await asyncio.sleep(1)
        r = await client.get(f"/api/ingestion-jobs/{job_id}", headers=h)
        if r.json()["status"] in {"done", "failed"}:
            assert r.json()["status"] == "done", r.json()
            return
    raise AssertionError("ingestion did not finish in 2 min")


@pytest.mark.integration
async def test_entity_run_and_calibrate(_clean_eval_tables: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=600.0
    ) as client:
        token, _tenant_id = await _register(client, "entity-run@example.com")
        cred_id = await _ollama_credential_id(client, token)
        headers = {"Authorization": f"Bearer {token}"}

        embedding_selection = {
            "credential_id": cred_id,
            "model_id": "bge-m3",
            "dim": 1024,
        }

        # 1. Create dataset (this also creates the KB via create_eval_dataset)
        create_ds = await client.post(
            "/api/admin/eval/datasets",
            headers=headers,
            json={
                "name": "Civil War DS",
                "description": "entity run test",
                "embedding_selection": embedding_selection,
            },
        )
        assert create_ds.status_code == 201, create_ds.text
        ds = create_ds.json()
        ds_id = ds["id"]
        kb_id = ds["knowledge_base_id"]
        assert kb_id, "dataset must have a KB"

        # 2. Upload tiny doc to the KB
        civil_war_doc = (
            b"The Spanish Civil War lasted from July 17, 1936 until April 1, 1939. "
            b"The Nationalists were led by General Francisco Franco. "
            b"Franco died in 1975, ending nearly four decades of dictatorship."
        )
        await _ingest_doc(client, token, kb_id, civil_war_doc)

        # 3. Import 1 row into the dataset
        jsonl = (
            '{"question": "When did the Spanish Civil War end?", '
            '"ground_truth": "1939", "scenario": "doc_only", "complexity": "factual"}'
        )
        imp = await client.post(
            f"/api/admin/eval/datasets/{ds_id}/rows/import",
            headers=headers,
            json={"jsonl": jsonl},
        )
        assert imp.status_code == 200, imp.text
        assert imp.json()["num_rows"] == 1

        # 4. Create chatbot linked to that KB
        r = await client.post(
            "/api/chatbots", headers=headers,
            json={
                "name": "EntityRunBot",
                "system_prompt": "Answer concisely using search_docs.",
                "llm_selection": {
                    "credential_id": cred_id,
                    "model_id": "llama3.1",
                },
                "kb_ids": [kb_id],
                "pipeline_config": {"top_k": 3, "max_self_correction_retries": 1},
                "widget_config": {},
            },
        )
        assert r.status_code == 201, r.text
        chatbot_id = r.json()["id"]

        # 5. POST /api/admin/eval/datasets/{ds_id}/runs → 202 Accepted
        run_resp = await client.post(
            f"/api/admin/eval/datasets/{ds_id}/runs",
            headers=headers,
            json={
                "chatbot_id": chatbot_id,
                "judge_credential_id": cred_id,
                "judge_model": "gemma3:1b",
            },
        )
        assert run_resp.status_code == 202, run_resp.text
        run_body = run_resp.json()
        run_id = run_body["id"]
        assert run_body["status"] in {"queued", "running"}

        # 6. Poll GET /api/admin/eval/runs/{run_id} until done or failed (max 5 min)
        final_status = None
        for _ in range(60):
            await asyncio.sleep(5)
            poll = await client.get(
                f"/api/admin/eval/runs/{run_id}", headers=headers
            )
            assert poll.status_code == 200, poll.text
            final_status = poll.json()["status"]
            if final_status in {"done", "failed"}:
                break

        assert final_status == "done", (
            f"eval run ended with status={final_status!r}; "
            f"last response: {poll.json()}"
        )
        run_data = poll.json()
        assert run_data["tokens_gen_in"] is not None or run_data["tokens_gen_in"] == 0

        # 7. POST /api/admin/eval/datasets/{ds_id}/calibrate → 200 OK
        cal_resp = await client.post(
            f"/api/admin/eval/datasets/{ds_id}/calibrate",
            headers=headers,
            json={
                "chatbot_id": chatbot_id,
                "judge_credential_id": cred_id,
                "judge_model": "gemma3:1b",
                "sample_size": 1,
            },
        )
        assert cal_resp.status_code == 200, cal_resp.text
        cal = cal_resp.json()
        assert cal["sample_size"] >= 1
        assert "avg_gen_tokens" in cal
        assert "avg_judge_tokens" in cal
        assert "avg_seconds" in cal
        assert "projected_total" in cal
        pt = cal["projected_total"]
        assert "tokens" in pt
        assert "seconds" in pt
