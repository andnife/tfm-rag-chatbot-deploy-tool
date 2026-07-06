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
    return body["access_token"], body["tenant_id"]


async def _ollama_cred_id(client: AsyncClient, token: str) -> str:
    r = await client.get(
        "/api/credentials",
        headers={"Authorization": f"Bearer {token}"},
    )
    return next(c for c in r.json() if c["provider_id"] == "ollama")["id"]


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

    for _ in range(120):  # up to 2 min
        await asyncio.sleep(1)
        r = await client.get(f"/api/ingestion-jobs/{job_id}", headers=h)
        assert r.status_code == 200
        if r.json()["status"] in {"done", "failed"}:
            assert r.json()["status"] == "done", r.json()
            return
    raise AssertionError(f"ingestion did not finish in 2 min: job={job_id}")


async def test_end_to_end_agent_loop_returns_grounded_answer(
    _clean_state: None,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=180.0) as client:
        token, _ = await _register(client, "demo-chat@example.com")
        h = {"Authorization": f"Bearer {token}"}
        cred_id = await _ollama_cred_id(client, token)

        # 1) Create a KB with the Ollama bge-m3 embedder
        r = await client.post(
            "/api/knowledge-bases", headers=h,
            json={
                "name": "DemoKB",
                "embedding_selection": {
                    "credential_id": cred_id,
                    "model_id": "bge-m3",
                    "dim": 1024,
                },
                "chunking_config": {
                    "strategy": "fixed",
                    "chunk_size": 300,
                    "chunk_overlap": 50,
                },
            },
        )
        assert r.status_code == 201, r.text
        kb_id = r.json()["id"]

        # 2) Ingest a short fact-laden doc
        body = (
            b"The Spanish Civil War lasted from July 17, 1936 until April 1, 1939. "
            b"It pitted the Republicans, who were loyal to the left-leaning Popular "
            b"Front government of the Second Spanish Republic, against the Nationalists, "
            b"a falangist, conservative, and largely Catholic group led by General "
            b"Francisco Franco. The Nationalists won the war. Franco then ruled Spain "
            b"as a dictator until his death in 1975.\n\n"
            b"Pineapples grow on a low plant in tropical climates."
        )
        await _ingest_doc(client, token, kb_id, body)

        # 3) Create a chatbot pointing at the KB, using Ollama llama3.1
        r = await client.post(
            "/api/chatbots", headers=h,
            json={
                "name": "HistoryBot",
                "system_prompt": (
                    "You are a concise history assistant. Ground your answers "
                    "in the available documents."
                ),
                "llm_selection": {
                    "credential_id": cred_id,
                    "model_id": "llama3.1",
                },
                "kb_ids": [kb_id],
                "pipeline_config": {
                    "top_k": 3,
                    "max_self_correction_retries": 3,
                },
                "widget_config": {},
            },
        )
        assert r.status_code == 201, r.text
        chatbot_id = r.json()["id"]

        # 4) Ask a question
        r = await client.post(
            f"/api/chatbots/{chatbot_id}/chat", headers=h,
            json={
                "message": "When did the Spanish Civil War end?",
            },
        )
        assert r.status_code == 200, r.text
        body_out = r.json()

        # Basic shape
        assert "session_id" in body_out
        assert "message_id" in body_out
        assert isinstance(body_out["content"], str) and body_out["content"].strip()
        assert isinstance(body_out["citations"], list)
        assert isinstance(body_out["iterations"], list)

        # The router classified this factual question as the `docs` route.
        tools_used = [it["tool"] for it in body_out["iterations"]]
        assert "docs" in tools_used, (
            f"Expected a docs route; iterations={body_out['iterations']}"
        )

        content_lower = body_out["content"].lower()
        abstained = content_lower.startswith("i don't know")
        if not abstained:
            assert "1939" in content_lower or "april" in content_lower, (
                f"Unexpected answer: {body_out['content']!r}"
            )
            assert body_out["citations"], "Grounded answer with no citations"
            assert any(
                c["source_name"] == "manual.txt" for c in body_out["citations"]
            )
        else:
            print(f"NOTE: model abstained: {body_out['content']!r}")

        # 5) Follow-up turn re-uses the same session_id
        first_session = body_out["session_id"]
        r = await client.post(
            f"/api/chatbots/{chatbot_id}/chat", headers=h,
            json={
                "session_id": first_session,
                "message": "Who led the Nationalists?",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["session_id"] == first_session

        # 6) The session now has 4 messages (user/assistant × 2)
        r = await client.get(f"/api/sessions/{first_session}", headers=h)
        assert r.status_code == 200
        messages = r.json()["messages"]
        assert len(messages) == 4
        assert [m["role"] for m in messages] == [
            "user", "assistant", "user", "assistant"
        ]


async def test_chat_on_unknown_chatbot_returns_404(_clean_state: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, _ = await _register(client, "ghost-chat@example.com")
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post(
            "/api/chatbots/00000000-0000-0000-0000-000000000000/chat",
            headers=h,
            json={"message": "hi"},
        )
        assert r.status_code == 404


async def test_chat_isolation_between_tenants(_clean_state: None) -> None:
    transport = ASGITransport(app=app)
    # One client per user: register sets an httpOnly cookie and the context
    # resolver prefers the cookie over the Authorization header, so a shared
    # cookie jar would make Alice's chatbot get created under Bob's tenant.
    async with (
        AsyncClient(transport=transport, base_url="http://test") as alice_client,
        AsyncClient(transport=transport, base_url="http://test") as bob_client,
    ):
        alice_token, _ = await _register(alice_client, "alice-chat@example.com")
        bob_token, _ = await _register(bob_client, "bob-chat@example.com")
        alice_cred = await _ollama_cred_id(alice_client, alice_token)

        # Alice creates an empty-KB chatbot
        r = await alice_client.post(
            "/api/knowledge-bases",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={
                "name": "EmptyKB",
                "embedding_selection": {
                    "credential_id": alice_cred,
                    "model_id": "bge-m3", "dim": 1024,
                },
            },
        )
        kb_id = r.json()["id"]

        r = await alice_client.post(
            "/api/chatbots",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={
                "name": "AliceBot",
                "system_prompt": "x",
                "llm_selection": {
                    "credential_id": alice_cred,
                    "model_id": "llama3.1",
                },
                "kb_ids": [kb_id],
                "widget_config": {},
            },
        )
        chatbot_id = r.json()["id"]

        # Bob tries to chat with Alice's chatbot → 404
        r = await bob_client.post(
            f"/api/chatbots/{chatbot_id}/chat",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={"message": "hi"},
        )
        assert r.status_code == 404
