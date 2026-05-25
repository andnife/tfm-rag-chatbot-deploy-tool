"""E2E for CAP-WIDGET-RUNTIME — public widget endpoints + static serving."""
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

import tfm_rag.infrastructure.api.dependencies as _deps
from tfm_rag.infrastructure.api.app import app
from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.persistence.models.chat_sessions import (
    ChatSessionRow,
)
from tfm_rag.infrastructure.settings import Settings

pytestmark = pytest.mark.integration


@pytest.fixture
async def _clean_state(settings: Settings) -> None:
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    async with factory() as s:
        await s.execute(text(
            "TRUNCATE chat_messages, chat_sessions, "
            "chatbot_knowledge_base, chatbots, ingestion_jobs, "
            "sources, knowledge_bases, provider_credentials, "
            "users, tenants RESTART IDENTITY CASCADE"
        ))
        await s.commit()
    await engine.dispose()
    _deps._session_factory = None


async def _bootstrap_chatbot(c: AsyncClient) -> dict[str, Any]:
    r = await c.post(
        "/api/auth/register",
        json={"email": "widget-e2e@example.com", "password": "correctpassword"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    h = {"Authorization": f"Bearer {token}"}

    creds = (await c.get("/api/credentials", headers=h)).json()
    cred_id = next(x for x in creds if x["provider_id"] == "ollama")["id"]

    r = await c.post(
        "/api/knowledge-bases", headers=h,
        json={
            "name": "WidgetKB",
            "embedding_selection": {
                "provider_id": "ollama", "credential_id": cred_id,
                "model_id": "bge-m3", "dim": 1024,
            },
            "chunking_config": {
                "strategy": "fixed", "chunk_size": 300, "chunk_overlap": 50,
            },
        },
    )
    kb_id = r.json()["id"]

    r = await c.post(
        "/api/chatbots", headers=h,
        json={
            "name": "WidgetBot",
            "system_prompt": "Sé conciso.",
            "llm_selection": {
                "provider_id": "ollama", "credential_id": cred_id,
                "model_id": "llama3.1",
            },
            "kb_ids": [kb_id],
            "pipeline_config": {"top_k": 3, "max_retrieval_iterations": 2},
            "widget_config": {
                "theme": "dark",
                "primary_color": "#10b981",
                "title": "TestBot",
                "welcome_message": "¡Hola!",
                "placeholder": "Pregunta...",
                "allowed_origins": ["https://acme.example.com"],
            },
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return {
        "chatbot_id": body["id"],
        "public_key": body["public_key"],
    }


async def test_widget_config_endpoint_returns_safe_subset(
    _clean_state: None,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        info = await _bootstrap_chatbot(c)
        r = await c.get(
            f"/api/public/chatbots/{info['public_key']}/config",
            headers={"Origin": "https://acme.example.com"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chatbot_id"] == info["chatbot_id"]
    assert body["name"] == "WidgetBot"
    w = body["widget"]
    assert w["theme"] == "dark"
    assert w["primary_color"] == "#10b981"
    assert w["title"] == "TestBot"
    assert w["welcome_message"] == "¡Hola!"
    assert "system_prompt" not in body  # MUST NOT leak

    # CORS allowed because Origin matches widget_config.allowed_origins
    assert r.headers.get("access-control-allow-origin") == (
        "https://acme.example.com"
    )


async def test_widget_config_returns_404_for_unknown_public_key(
    _clean_state: None,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/public/chatbots/wgt_bogus/config")
    assert r.status_code == 404


async def test_widget_cors_does_not_echo_unknown_origin(
    _clean_state: None,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        info = await _bootstrap_chatbot(c)
        r = await c.get(
            f"/api/public/chatbots/{info['public_key']}/config",
            headers={"Origin": "https://attacker.example.com"},
        )
    # The endpoint still returns 200 — CORS narrowing is enforced by the
    # BROWSER reading the Access-Control-Allow-Origin header. We assert
    # the header is absent or doesn't match the attacker.
    allowed = r.headers.get("access-control-allow-origin")
    assert allowed != "https://attacker.example.com"


async def test_widget_chat_creates_widget_session_and_round_trip(
    _clean_state: None, settings: Settings,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=120.0,
    ) as c:
        info = await _bootstrap_chatbot(c)
        cookie = "test-cookie-" + "abcd" * 6
        r = await c.post(
            f"/api/public/chatbots/{info['public_key']}/chat",
            json={
                "session_id": None,
                "public_session_cookie": cookie,
                "message": "Hola, ¿qué puedes hacer?",
            },
            headers={"Origin": "https://acme.example.com"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["content"], "non-empty answer"
    session_id_str = body["session_id"]

    # Verify the chat_session row has origin="widget" + cookie.
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    async with factory() as s:
        row = (
            await s.execute(
                select(ChatSessionRow).where(
                    ChatSessionRow.id == UUID(session_id_str)
                )
            )
        ).scalar_one()
        assert row.origin == "widget"
        assert row.public_session_cookie == cookie
    await engine.dispose()


async def test_widget_chat_rejects_wrong_cookie_on_session_reuse(
    _clean_state: None,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=120.0,
    ) as c:
        info = await _bootstrap_chatbot(c)
        cookie = "good-cookie-" + "x" * 32
        r1 = await c.post(
            f"/api/public/chatbots/{info['public_key']}/chat",
            json={
                "session_id": None,
                "public_session_cookie": cookie,
                "message": "Primera",
            },
        )
        assert r1.status_code == 200, r1.text
        session_id = r1.json()["session_id"]

        # Replay with the WRONG cookie — must 403.
        r2 = await c.post(
            f"/api/public/chatbots/{info['public_key']}/chat",
            json={
                "session_id": session_id,
                "public_session_cookie": "wrong-cookie",
                "message": "Segunda",
            },
        )
    assert r2.status_code == 403
    assert "cookie" in r2.json()["detail"].lower()


async def test_widget_js_is_served_as_static_file(_clean_state: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/widget/widget.js")
    assert r.status_code == 200, r.text
    # Verify it actually looks like our widget.
    body_text = r.text
    assert "TFM RAG Chatbot Widget" in body_text
    assert "data-public-key" in body_text
    assert "shadowRoot" in body_text or "attachShadow" in body_text
