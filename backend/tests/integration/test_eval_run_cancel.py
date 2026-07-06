"""Integration tests for the eval-run cancel endpoint.

POST /api/admin/eval/runs/{run_id}/cancel

Tests:
- Cancelling a 'running' run returns 200 + status becomes 'cancelled'.
- Cancelling a 'done' run returns 409.
- Cancelling a missing run returns 404.

These tests insert rows directly via the ORM (no background eval job needed),
so they run fast and do not require Ollama/Qdrant.
"""
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import tfm_rag.infrastructure.api.dependencies as _deps
from tfm_rag.infrastructure.api.app import app
from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.persistence.models.eval_runs import EvalRunRow
from tfm_rag.infrastructure.settings import Settings, get_settings

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
async def _clean_tables(settings: Settings) -> None:
    """Truncate relevant tables to avoid cross-test contamination."""
    _deps._session_factory = None
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    async with factory() as s:
        await s.execute(
            text(
                "TRUNCATE eval_runs, chatbots, provider_credentials, "
                "users, tenants RESTART IDENTITY CASCADE"
            )
        )
        await s.commit()
    await engine.dispose()


async def _register_superadmin(client: AsyncClient, email: str) -> tuple[str, str]:
    """Register a user, grant superadmin, re-login, return (token, tenant_id)."""
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!"},
    )
    assert r.status_code == 201, r.text

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
        json={"email": email, "password": "TestPass123!"},
    )
    assert relogin.status_code == 200, relogin.text
    body = relogin.json()
    return body["access_token"], body["tenant_id"]


async def _create_chatbot(client: AsyncClient, token: str) -> str:
    """Create a minimal chatbot (no KB); return its id."""
    r = await client.get(
        "/api/credentials",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    creds = r.json()
    ollama = next(c for c in creds if c["provider_id"] == "ollama")
    cred_id = ollama["id"]

    r = await client.post(
        "/api/chatbots",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "CancelTestBot",
            "system_prompt": "Answer questions.",
            "llm_selection": {
                "credential_id": cred_id,
                "model_id": "llama3.1",
            },
            "kb_ids": [],
            "pipeline_config": {},
            "widget_config": {},
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _insert_run_row(
    tenant_id: str, chatbot_id: str, status: str
) -> str:
    """Insert an eval_runs row directly via ORM; return the run id."""
    engine = build_engine(get_settings().postgres_url)
    factory = build_session_factory(engine)
    run_id = uuid4()
    async with factory() as s:
        row = EvalRunRow(
            id=run_id,
            tenant_id=tenant_id,
            chatbot_id=chatbot_id,
            judge_model="gemma3:1b",
            status=status,
        )
        s.add(row)
        await s.commit()
    await engine.dispose()
    return str(run_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_cancel_running_run(_clean_tables: None) -> None:
    """POST /runs/{id}/cancel on a 'running' row → 200 + status becomes cancelled."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:
        token, tenant_id = await _register_superadmin(client, "cancel-test@example.com")
        chatbot_id = await _create_chatbot(client, token)

        run_id = await _insert_run_row(tenant_id, chatbot_id, "running")

        resp = await client.post(
            f"/api/admin/eval/runs/{run_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "cancelled"}

        # Verify DB row was updated
        poll = await client.get(
            f"/api/admin/eval/runs/{run_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert poll.status_code == 200, poll.text
        assert poll.json()["status"] == "cancelled"
        assert poll.json()["finished_at"] is not None


@pytest.mark.integration
async def test_cancel_queued_run(_clean_tables: None) -> None:
    """POST /runs/{id}/cancel on a 'queued' row → 200 + status becomes cancelled."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:
        token, tenant_id = await _register_superadmin(client, "cancel-queued@example.com")
        chatbot_id = await _create_chatbot(client, token)

        run_id = await _insert_run_row(tenant_id, chatbot_id, "queued")

        resp = await client.post(
            f"/api/admin/eval/runs/{run_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "cancelled"}


@pytest.mark.integration
async def test_cancel_done_run_returns_409(_clean_tables: None) -> None:
    """POST /runs/{id}/cancel on a 'done' row → 409 Conflict."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:
        token, tenant_id = await _register_superadmin(client, "cancel-done@example.com")
        chatbot_id = await _create_chatbot(client, token)

        run_id = await _insert_run_row(tenant_id, chatbot_id, "done")

        resp = await client.post(
            f"/api/admin/eval/runs/{run_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 409, resp.text
        assert "done" in resp.json()["detail"]


@pytest.mark.integration
async def test_cancel_failed_run_returns_409(_clean_tables: None) -> None:
    """POST /runs/{id}/cancel on a 'failed' row → 409 Conflict."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:
        token, tenant_id = await _register_superadmin(client, "cancel-failed@example.com")
        chatbot_id = await _create_chatbot(client, token)

        run_id = await _insert_run_row(tenant_id, chatbot_id, "failed")

        resp = await client.post(
            f"/api/admin/eval/runs/{run_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 409, resp.text
        assert "failed" in resp.json()["detail"]


@pytest.mark.integration
async def test_cancel_missing_run_returns_404(_clean_tables: None) -> None:
    """POST /runs/{id}/cancel for a non-existent run → 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:
        token, _tenant_id = await _register_superadmin(client, "cancel-missing@example.com")

        fake_id = uuid4()
        resp = await client.post(
            f"/api/admin/eval/runs/{fake_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_live_endpoint_returns_empty_when_no_file(_clean_tables: None) -> None:
    """GET /runs/{id}/live returns {} when no live.json exists."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:
        token, tenant_id = await _register_superadmin(client, "live-test@example.com")
        chatbot_id = await _create_chatbot(client, token)
        run_id = await _insert_run_row(tenant_id, chatbot_id, "running")

        resp = await client.get(
            f"/api/admin/eval/runs/{run_id}/live",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {}


@pytest.mark.integration
async def test_live_endpoint_missing_run_returns_404(_clean_tables: None) -> None:
    """GET /runs/{id}/live for a run not owned by the tenant → 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:
        token, _tenant_id = await _register_superadmin(client, "live-missing@example.com")

        fake_id = uuid4()
        resp = await client.get(
            f"/api/admin/eval/runs/{fake_id}/live",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404, resp.text
