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
async def _clean_state(settings: Settings) -> None:
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    async with factory() as s:
        await s.execute(text(
            "TRUNCATE chatbot_knowledge_base, chatbots, ingestion_jobs, "
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
    assert r.status_code == 200, r.text
    return next(c for c in r.json() if c["provider_id"] == "ollama")["id"]


async def _create_kb(
    client: AsyncClient, token: str, name: str, dim: int, model_id: str
) -> str:
    cred = await _ollama_cred_id(client, token)
    r = await client.post(
        "/api/knowledge-bases",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": name,
            "embedding_selection": {
                "credential_id": cred,
                "model_id": model_id,
                "dim": dim,
            },
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.integration
async def test_chatbot_full_lifecycle(_clean_state: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, _ = await _register(client, "bot-owner@example.com")
        cred = await _ollama_cred_id(client, token)
        h = {"Authorization": f"Bearer {token}"}

        # 0-KB chatbot
        r = await client.post(
            "/api/chatbots", headers=h,
            json={
                "name": "LLM-only",
                "system_prompt": "Be concise.",
                "llm_selection": {
                    "credential_id": cred,
                    "model_id": "llama3.1",
                },
                "kb_ids": [],
                "widget_config": {"theme": "light"},
            },
        )
        assert r.status_code == 201, r.text
        bot1 = r.json()
        assert bot1["kb_ids"] == []
        assert bot1["pipeline_config"]["max_self_correction_retries"] == 1

        # KB + chatbot with KB
        kb1 = await _create_kb(client, token, "Manuals", 1024, "bge-m3")
        r = await client.post(
            "/api/chatbots", headers=h,
            json={
                "name": "ManualsBot",
                "system_prompt": "Answer with citations.",
                "llm_selection": {
                    "credential_id": cred,
                    "model_id": "llama3.1",
                },
                "kb_ids": [kb1],
                "widget_config": {},
            },
        )
        assert r.status_code == 201, r.text
        bot2 = r.json()
        assert bot2["kb_ids"] == [kb1]

        # Duplicate name → 409
        r = await client.post(
            "/api/chatbots", headers=h,
            json={
                "name": "ManualsBot",
                "system_prompt": "x",
                "llm_selection": {
                    "credential_id": cred,
                    "model_id": "llama3.1",
                },
                "kb_ids": [],
                "widget_config": {},
            },
        )
        assert r.status_code == 409, r.text

        # List
        r = await client.get("/api/chatbots", headers=h)
        assert r.status_code == 200
        ids = {b["id"] for b in r.json()}
        assert {bot1["id"], bot2["id"]} <= ids

        # Get
        r = await client.get(f"/api/chatbots/{bot2['id']}", headers=h)
        assert r.status_code == 200
        assert r.json()["kb_ids"] == [kb1]

        # Patch — change name + pipeline_config.max_self_correction_retries
        r = await client.patch(
            f"/api/chatbots/{bot2['id']}", headers=h,
            json={
                "name": "ManualsBot v2",
                "pipeline_config": {
                    "top_k": 7,
                    "max_self_correction_retries": 3,
                    "score_threshold": 0.2,
                    "enable_reranker": False,
                    "reranker_initial_top_k": 30,
                    "abstain_when_insufficient": True,
                    "generation": {
                        "temperature": 0.1,
                        "top_p": 0.95,
                        "max_tokens": 2048,
                    },
                },
            },
        )
        assert r.status_code == 200, r.text
        patched = r.json()
        assert patched["name"] == "ManualsBot v2"
        assert patched["pipeline_config"]["max_self_correction_retries"] == 3

        # Delete
        r = await client.delete(f"/api/chatbots/{bot1['id']}", headers=h)
        assert r.status_code == 204
        r = await client.get(f"/api/chatbots/{bot1['id']}", headers=h)
        assert r.status_code == 404


@pytest.mark.integration
async def test_chatbot_rejects_incompatible_embeddings(_clean_state: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, _ = await _register(client, "owner2@example.com")
        cred = await _ollama_cred_id(client, token)
        h = {"Authorization": f"Bearer {token}"}

        kb_1024 = await _create_kb(client, token, "KB-1024", 1024, "bge-m3")
        kb_768 = await _create_kb(
            client, token, "KB-768", 768, "nomic-embed-text"
        )

        r = await client.post(
            "/api/chatbots", headers=h,
            json={
                "name": "MixedBot",
                "system_prompt": "x",
                "llm_selection": {
                    "credential_id": cred,
                    "model_id": "llama3.1",
                },
                "kb_ids": [kb_1024, kb_768],
                "widget_config": {},
            },
        )
        assert r.status_code == 409
        assert "embedding" in r.json()["detail"].lower()


@pytest.mark.integration
async def test_delete_kb_referenced_by_chatbot_returns_409(_clean_state: None) -> None:
    """Verifies that plan #7's KnowledgeBaseInUseError mapping fires once
    the RESTRICT FK exists.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, _ = await _register(client, "owner3@example.com")
        cred = await _ollama_cred_id(client, token)
        h = {"Authorization": f"Bearer {token}"}

        kb = await _create_kb(client, token, "Locked", 1024, "bge-m3")
        r = await client.post(
            "/api/chatbots", headers=h,
            json={
                "name": "Bot",
                "system_prompt": "x",
                "llm_selection": {
                    "credential_id": cred,
                    "model_id": "llama3.1",
                },
                "kb_ids": [kb],
                "widget_config": {},
            },
        )
        assert r.status_code == 201, r.text
        bot_id = r.json()["id"]

        # Try to delete the KB → 409
        r = await client.delete(f"/api/knowledge-bases/{kb}", headers=h)
        assert r.status_code == 409, r.text
        assert "referenc" in r.json()["detail"].lower()

        # Delete the chatbot first; THEN the KB delete succeeds
        r = await client.delete(f"/api/chatbots/{bot_id}", headers=h)
        assert r.status_code == 204
        r = await client.delete(f"/api/knowledge-bases/{kb}", headers=h)
        assert r.status_code == 204


@pytest.mark.integration
async def test_chatbot_isolation_between_tenants(_clean_state: None) -> None:
    transport = ASGITransport(app=app)
    # Separate clients per user: register sets an httpOnly auth cookie, and the
    # context resolver prefers the cookie over the Bearer header. A shared
    # cookie jar would make every request use whoever registered last; distinct
    # clients mirror real per-browser isolation.
    async with (
        AsyncClient(transport=transport, base_url="http://test") as alice_client,
        AsyncClient(transport=transport, base_url="http://test") as bob_client,
    ):
        alice_token, _ = await _register(alice_client, "alice-bot@example.com")
        bob_token, _ = await _register(bob_client, "bob-bot@example.com")
        alice_cred = await _ollama_cred_id(alice_client, alice_token)

        # Alice creates a chatbot
        r = await alice_client.post(
            "/api/chatbots",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={
                "name": "Alice Bot",
                "system_prompt": "x",
                "llm_selection": {
                    "credential_id": alice_cred,
                    "model_id": "llama3.1",
                },
                "kb_ids": [],
                "widget_config": {},
            },
        )
        assert r.status_code == 201
        bot_id = r.json()["id"]

        # Bob cannot see it
        r = await bob_client.get(
            "/api/chatbots",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert r.status_code == 200
        assert r.json() == []

        # Nor fetch it by id
        r = await bob_client.get(
            f"/api/chatbots/{bot_id}",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert r.status_code == 404


@pytest.mark.integration
async def test_public_key_generated_and_immutable(_clean_state: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token, _ = await _register(c, "widget-test@example.com")
        h = {"Authorization": f"Bearer {token}"}
        cred_id = await _ollama_cred_id(c, token)

        # Create a chatbot — no widget_config sent (relies on defaults)
        r = await c.post(
            "/api/chatbots",
            headers=h,
            json={
                "name": "PublicKeyBot",
                "system_prompt": "be brief",
                "llm_selection": {
                    "credential_id": cred_id,
                    "model_id": "llama3.1",
                },
                "kb_ids": [],
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        chatbot_id = body["id"]
        public_key = body["public_key"]
        assert isinstance(public_key, str)
        assert public_key.startswith("wgt_")
        assert len(public_key) > 10

        # GET returns the same public_key
        r2 = await c.get(f"/api/chatbots/{chatbot_id}", headers=h)
        assert r2.status_code == 200, r2.text
        assert r2.json()["public_key"] == public_key

        # PATCH with a "public_key" in the body — server should either reject
        # (422) or silently ignore it; either way the stored key must not change.
        r3 = await c.patch(
            f"/api/chatbots/{chatbot_id}",
            headers=h,
            json={"public_key": "wgt_attacker"},
        )
        # 422 (extra field rejected) or 200 (ignored) are both acceptable.
        assert r3.status_code in (200, 422), r3.text

        # Re-read: public_key must be unchanged.
        r4 = await c.get(f"/api/chatbots/{chatbot_id}", headers=h)
        assert r4.status_code == 200, r4.text
        assert r4.json()["public_key"] == public_key


@pytest.mark.integration
async def test_chatbot_role_llm_selections_roundtrip(_clean_state: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        token, _ = await _register(client, "roles@example.com")
        cred = await _ollama_cred_id(client, token)
        headers = {"Authorization": f"Bearer {token}"}

        # Create with only the evaluator role overridden.
        r = await client.post(
            "/api/chatbots",
            headers=headers,
            json={
                "name": "roles-bot",
                "system_prompt": "sp",
                "llm_selection": {
                    "credential_id": cred, "model_id": "llama3.1",
                },
                "role_llm_selections": {
                    "evaluator": {
                        "credential_id": cred, "model_id": "llama3.1",
                    }
                },
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert set(body["role_llm_selections"].keys()) == {"evaluator"}
        cid = body["id"]

        # GET reflects it.
        g = await client.get(f"/api/chatbots/{cid}", headers=headers)
        assert g.json()["role_llm_selections"]["evaluator"]["model_id"] == "llama3.1"

        # PATCH adds sql_generator.
        p = await client.patch(
            f"/api/chatbots/{cid}",
            headers=headers,
            json={"role_llm_selections": {
                "sql_generator": {
                    "credential_id": cred, "model_id": "llama3.1",
                }
            }},
        )
        assert p.status_code == 200, p.text
        assert set(p.json()["role_llm_selections"].keys()) == {"sql_generator"}

        # provider_id is accept-ignored in the new selection shape, so a bad
        # provider no longer 4xxs. A genuinely malformed selection still does:
        # a non-UUID credential_id fails request validation (422).
        bad = await client.post(
            "/api/chatbots",
            headers=headers,
            json={
                "name": "bad-bot",
                "system_prompt": "sp",
                "llm_selection": {
                    "credential_id": "not-a-uuid", "model_id": "llama3.1",
                },
            },
        )
        assert bad.status_code in (400, 422), bad.text
