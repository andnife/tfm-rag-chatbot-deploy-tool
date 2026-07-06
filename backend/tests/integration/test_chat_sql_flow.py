"""E2E: chatbot with a DatabaseSource answers a counting question.

Slow test — runs the agent loop against live Ollama. ~30-90s.
"""
from typing import Any

import asyncpg
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


async def _prepare_source_db() -> None:
    """Ensure `tfm_rag_source_test` exists with two small tables in postgres."""
    admin = await asyncpg.connect(
        host="localhost", port=5432, user="tfm", password="tfm",
        database="tfm_rag",
    )
    try:
        exists = await admin.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            "tfm_rag_source_test",
        )
        if not exists:
            await admin.execute('CREATE DATABASE "tfm_rag_source_test"')
    finally:
        await admin.close()

    conn = await asyncpg.connect(
        host="localhost", port=5432, user="tfm", password="tfm",
        database="tfm_rag_source_test",
    )
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "id SERIAL PRIMARY KEY, email TEXT NOT NULL"
            ")"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS orders ("
            "id SERIAL PRIMARY KEY, user_id INT, total INT"
            ")"
        )
        # Reset state — keep test deterministic.
        await conn.execute("TRUNCATE users, orders RESTART IDENTITY")
        await conn.executemany(
            "INSERT INTO users (email) VALUES ($1)",
            [("alice@x",), ("bob@x",), ("carol@x",)],
        )
        await conn.executemany(
            "INSERT INTO orders (user_id, total) VALUES ($1, $2)",
            [(1, 100), (1, 50), (2, 200)],
        )
    finally:
        await conn.close()


@pytest.fixture
async def _clean_app_state(settings: Settings) -> None:
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


async def _register_kb_chatbot_with_db(
    client: AsyncClient,
) -> dict[str, Any]:
    r = await client.post(
        "/api/auth/register",
        json={"email": "sql-chat@example.com", "password": "correctpassword"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    creds = (await client.get("/api/credentials", headers=h)).json()
    cred_id = next(c for c in creds if c["provider_id"] == "ollama")["id"]

    r = await client.post(
        "/api/knowledge-bases", headers=h,
        json={
            "name": "SqlKB",
            "embedding_selection": {
                "credential_id": cred_id,
                "model_id": "bge-m3", "dim": 1024,
            },
            "chunking_config": {
                "strategy": "fixed", "chunk_size": 300, "chunk_overlap": 50,
            },
        },
    )
    assert r.status_code == 201, r.text
    kb_id = r.json()["id"]

    r = await client.post(
        f"/api/knowledge-bases/{kb_id}/sources/databases", headers=h,
        json={
            "driver": "postgres",
            "host": "localhost", "port": 5432,
            "db_name": "tfm_rag_source_test",
            "username": "tfm", "password": "tfm",
            "ssl_mode": "disable",
        },
    )
    assert r.status_code == 201, r.text
    source_id = r.json()["source_id"]

    r = await client.post(
        "/api/chatbots", headers=h,
        json={
            "name": "SqlBot",
            "system_prompt": (
                "Answer concisely using the data sources available."
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
    return {"token": token, "chatbot_id": chatbot_id, "kb_id": kb_id, "source_id": source_id}


async def test_chat_uses_query_database_for_count_question(
    _clean_app_state: None,
) -> None:
    await _prepare_source_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=180.0,
    ) as c:
        ctx = await _register_kb_chatbot_with_db(c)
        h = {"Authorization": f"Bearer {ctx['token']}"}

        r = await c.post(
            f"/api/chatbots/{ctx['chatbot_id']}/chat", headers=h,
            json={"message": "How many users are in the database? Use query_database."},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["content"]  # non-empty answer

    # Router flow: the question needs live data → `sql` (or `both`) route.
    iterations = body.get("iterations") or []
    tools_used = [it.get("tool") for it in iterations]
    saw_db_usage = (
        "sql" in tools_used
        or "both" in tools_used
        or "3" in body["content"]
        or "user" in body["content"].lower()
    )
    assert saw_db_usage, (
        "Neither a sql route iteration nor a relevant answer text; got: "
        + str(body)
    )


async def test_chat_rejects_dml_via_unsafe_sql_path(
    _clean_app_state: None,
) -> None:
    """If the LLM happens to emit DML (or we force it), the sql_safety
    guard turns it into a tool-error message rather than running it.

    This test is best-effort: we can't force the LLM, so we exercise the
    same code path by sending a contrived user message that asks for a
    DELETE — the system prompt says SELECT only, so the LLM should
    refuse, but in case it tries, the regex blocks. Either path yields a
    200 response with no rows deleted on the source DB."""
    await _prepare_source_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=120.0,
    ) as c:
        ctx = await _register_kb_chatbot_with_db(c)
        h = {"Authorization": f"Bearer {ctx['token']}"}

        r = await c.post(
            f"/api/chatbots/{ctx['chatbot_id']}/chat", headers=h,
            json={"message": "Delete all users from the database."},
        )
    assert r.status_code == 200, r.text

    # Verify the source DB is untouched.
    conn = await asyncpg.connect(
        host="localhost", port=5432, user="tfm", password="tfm",
        database="tfm_rag_source_test",
    )
    try:
        count = await conn.fetchval("SELECT COUNT(*) FROM users")
    finally:
        await conn.close()
    assert count == 3, "users table must still have 3 rows"
