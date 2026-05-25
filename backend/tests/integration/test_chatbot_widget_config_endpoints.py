"""Integration tests for widget config + public_key + CORS scaffolding."""
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
            "chatbot_knowledge_base, chatbots, "
            "sources, knowledge_bases, provider_credentials, "
            "users, tenants RESTART IDENTITY CASCADE"
        ))
        await s.commit()
    await engine.dispose()
    _deps._session_factory = None


async def _register_and_make_chatbot(c: AsyncClient) -> dict:
    r = await c.post(
        "/api/auth/register",
        json={"email": "widget-cfg@example.com", "password": "correctpassword"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    creds = (await c.get("/api/credentials", headers=h)).json()
    cred_id = next(cr for cr in creds if cr["provider_id"] == "ollama")["id"]
    r = await c.post(
        "/api/chatbots", headers=h,
        json={
            "name": "WidgetBot",
            "system_prompt": "be brief",
            "llm_selection": {
                "provider_id": "ollama", "credential_id": cred_id,
                "model_id": "llama3.1",
            },
            "kb_ids": [],
            "pipeline_config": {"top_k": 3, "max_retrieval_iterations": 3},
            "widget_config": {
                "theme": "dark",
                "primary_color": "#10b981",
                "title": "Asistente WidgetBot",
                "allowed_origins": ["https://acme.example.com"],
            },
        },
    )
    assert r.status_code == 201, r.text
    return {"token": token, "body": r.json()}


async def test_create_chatbot_structured_widget_config_round_trips(
    _clean_state: None,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        info = await _register_and_make_chatbot(c)
        body = info["body"]
        assert body["widget_config"]["theme"] == "dark"
        assert body["widget_config"]["primary_color"] == "#10b981"
        assert body["widget_config"]["title"] == "Asistente WidgetBot"
        assert body["widget_config"]["allowed_origins"] == [
            "https://acme.example.com"
        ]
        # defaults filled in:
        assert body["widget_config"]["position"] == "bottom-right"
        assert body["widget_config"]["welcome_message"]
        assert body["widget_config"]["placeholder"]

        # public_key generated
        assert body["public_key"].startswith("wgt_")


async def test_widget_config_validation_rejects_bad_color(
    _clean_state: None,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/auth/register",
            json={"email": "w2@example.com", "password": "correctpassword"},
        )
        token = r.json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        creds = (await c.get("/api/credentials", headers=h)).json()
        cred_id = next(cr for cr in creds if cr["provider_id"] == "ollama")["id"]

        # Bad hex color → 422 (Pydantic regex) OR 400 (domain validation).
        r = await c.post(
            "/api/chatbots", headers=h,
            json={
                "name": "Bad", "system_prompt": "p",
                "llm_selection": {
                    "provider_id": "ollama", "credential_id": cred_id,
                    "model_id": "llama3.1",
                },
                "kb_ids": [],
                "pipeline_config": {"top_k": 3, "max_retrieval_iterations": 3},
                "widget_config": {"primary_color": "blue"},
            },
        )
        assert r.status_code in (400, 422)


async def test_cors_preflight_allowed_for_public_paths(
    _clean_state: None,
) -> None:
    """A browser preflight from any origin to /api/public/anything must
    return 200 with CORS headers (plan #16 will narrow per chatbot)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.request(
            "OPTIONS", "/api/public/foo",
            headers={
                "Origin": "https://acme.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        # FastAPI's CORSMiddleware returns 200 with appropriate headers
        # for preflight. The exact status code is not the only signal —
        # the header `Access-Control-Allow-Origin` MUST be present.
        assert "access-control-allow-origin" in {
            k.lower() for k in r.headers
        }
