import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import tfm_rag.infrastructure.api.dependencies as _deps
from tfm_rag.application.chat.append_message import append_message
from tfm_rag.application.chat.create_session import create_session
from tfm_rag.infrastructure.api.app import app
from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.settings import Settings


@pytest.fixture
async def _clean_state(settings: Settings) -> None:
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    async with factory() as s:
        await s.execute(text(
            "TRUNCATE chat_messages, chat_sessions, "
            "chatbot_knowledge_base, chatbots, ingestion_jobs, "
            "sources, knowledge_bases, provider_credentials, users, tenants "
            "RESTART IDENTITY CASCADE"
        ))
        await s.commit()
    await engine.dispose()
    _deps._session_factory = None


async def _register(client: AsyncClient, email: str) -> tuple[str, str]:
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "correctpassword"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return body["token"], body["tenant_id"]


async def _ollama_cred_id(client: AsyncClient, token: str) -> str:
    r = await client.get(
        "/api/credentials",
        headers={"Authorization": f"Bearer {token}"},
    )
    return next(c for c in r.json() if c["provider_id"] == "ollama")["id"]


async def _create_chatbot(
    client: AsyncClient, token: str, name: str
) -> str:
    cred = await _ollama_cred_id(client, token)
    r = await client.post(
        "/api/chatbots",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": name,
            "system_prompt": "x",
            "llm_selection": {
                "provider_id": "ollama",
                "credential_id": cred,
                "model_id": "llama3.1",
            },
            "kb_ids": [],
            "widget_config": {},
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.integration
async def test_list_and_get_session_after_seeding(
    _clean_state: None, settings: Settings
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, tenant_id_str = await _register(client, "ses-owner@example.com")
        chatbot_id_str = await _create_chatbot(client, token, "Bot")
        h = {"Authorization": f"Bearer {token}"}

        # Seed: open a session and append 3 messages via the internal helpers.
        engine = build_engine(settings.postgres_url)
        factory = build_session_factory(engine)
        from uuid import UUID

        ctx = RequestContext(
            tenant_id=UUID(tenant_id_str),
            user_id=None,
        )
        async with factory() as db:
            session_id = await create_session(
                db, ctx,
                chatbot_id=UUID(chatbot_id_str),
                origin="playground",
                public_session_cookie=None,
            )
            await append_message(
                db, ctx,
                session_id=session_id,
                role="user", content="hello there",
                citations=None, metadata=None,
            )
            await append_message(
                db, ctx,
                session_id=session_id,
                role="assistant", content="hi! how can I help?",
                citations=[
                    {
                        "source_id": "00000000-0000-0000-0000-000000000000",
                        "source_name": "fake.txt",
                        "location": "p1",
                        "chunk_id": "c0",
                        "score": 0.91,
                    }
                ],
                metadata={"iterations": [{"index": 0, "tool": "final_answer"}]},
            )
            await append_message(
                db, ctx,
                session_id=session_id,
                role="user", content="thanks",
                citations=None, metadata=None,
            )
            await db.commit()
        await engine.dispose()

        # List sessions for this chatbot
        r = await client.get(
            f"/api/chatbots/{chatbot_id_str}/sessions", headers=h
        )
        assert r.status_code == 200, r.text
        sessions_list = r.json()
        assert len(sessions_list) == 1
        assert sessions_list[0]["id"] == str(session_id)
        assert sessions_list[0]["origin"] == "playground"

        # Get session detail
        r = await client.get(f"/api/sessions/{session_id}", headers=h)
        assert r.status_code == 200, r.text
        detail = r.json()
        assert detail["session"]["id"] == str(session_id)
        assert len(detail["messages"]) == 3
        # Messages are ordered by created_at ascending — user first, then
        # assistant, then user again.
        assert detail["messages"][0]["role"] == "user"
        assert detail["messages"][0]["content"] == "hello there"
        assert detail["messages"][1]["role"] == "assistant"
        assert detail["messages"][1]["citations"][0]["score"] == 0.91
        assert detail["messages"][1]["metadata"]["iterations"][0]["tool"] == "final_answer"
        assert detail["messages"][2]["role"] == "user"


@pytest.mark.integration
async def test_list_sessions_for_unknown_chatbot_returns_404(
    _clean_state: None,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, _ = await _register(client, "404@example.com")
        h = {"Authorization": f"Bearer {token}"}

        r = await client.get(
            "/api/chatbots/00000000-0000-0000-0000-000000000000/sessions",
            headers=h,
        )
        assert r.status_code == 404


@pytest.mark.integration
async def test_get_session_isolation_between_tenants(
    _clean_state: None, settings: Settings
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        alice_token, alice_tenant = await _register(
            client, "alice-ses@example.com"
        )
        bob_token, _ = await _register(client, "bob-ses@example.com")
        chatbot_id_str = await _create_chatbot(client, alice_token, "AliceBot")

        # Alice opens a session
        from uuid import UUID

        engine = build_engine(settings.postgres_url)
        factory = build_session_factory(engine)
        ctx = RequestContext(
            tenant_id=UUID(alice_tenant), user_id=None
        )
        async with factory() as db:
            session_id = await create_session(
                db, ctx,
                chatbot_id=UUID(chatbot_id_str),
                origin="playground",
                public_session_cookie=None,
            )
            await db.commit()
        await engine.dispose()

        # Bob tries to read it → 404
        r = await client.get(
            f"/api/sessions/{session_id}",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert r.status_code == 404


@pytest.mark.integration
async def test_delete_chatbot_cascades_sessions_and_messages(
    _clean_state: None, settings: Settings
) -> None:
    """Verifies the spec's 'DeleteChatbot cascada sesiones + mensajes'
    is now real (CASCADE FKs added in plan #14).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, tenant_id_str = await _register(client, "casc@example.com")
        chatbot_id_str = await _create_chatbot(client, token, "ToBeDeleted")
        h = {"Authorization": f"Bearer {token}"}

        from uuid import UUID

        engine = build_engine(settings.postgres_url)
        factory = build_session_factory(engine)
        ctx = RequestContext(
            tenant_id=UUID(tenant_id_str), user_id=None
        )
        async with factory() as db:
            session_id = await create_session(
                db, ctx,
                chatbot_id=UUID(chatbot_id_str),
                origin="playground",
                public_session_cookie=None,
            )
            await append_message(
                db, ctx,
                session_id=session_id,
                role="user", content="will be cascaded",
                citations=None, metadata=None,
            )
            await db.commit()
        await engine.dispose()

        # Delete the chatbot
        r = await client.delete(f"/api/chatbots/{chatbot_id_str}", headers=h)
        assert r.status_code == 204

        # Session is gone (cascade)
        r = await client.get(f"/api/sessions/{session_id}", headers=h)
        assert r.status_code == 404
