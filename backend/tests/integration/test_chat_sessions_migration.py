import asyncio
import subprocess

import pytest
from sqlalchemy import inspect

from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings


@pytest.mark.integration
async def test_migration_0007_creates_chat_tables(settings: Settings) -> None:
    result = await asyncio.to_thread(
        subprocess.run,
        ["alembic", "upgrade", "head"],
        cwd=".",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    engine = build_engine(settings.postgres_url)
    build_session_factory(engine)
    async with engine.connect() as conn:
        tables = await conn.run_sync(
            lambda sc: inspect(sc).get_table_names()
        )
        assert "chat_sessions" in tables
        assert "chat_messages" in tables

        s_cols = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("chat_sessions")}
        )
        assert {
            "id", "chatbot_id", "tenant_id", "origin",
            "public_session_cookie", "created_at", "last_activity_at",
        } <= s_cols

        m_cols = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("chat_messages")}
        )
        assert {
            "id", "session_id", "role", "content",
            "citations", "metadata", "created_at",
        } <= m_cols
    await engine.dispose()
