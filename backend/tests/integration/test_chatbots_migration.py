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
async def test_migration_0006_creates_chatbots_and_n2m(settings: Settings) -> None:
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
        assert "chatbots" in tables
        assert "chatbot_knowledge_base" in tables

        chatbot_cols = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("chatbots")}
        )
        assert {
            "id", "tenant_id", "name", "description",
            "system_prompt", "llm_selection", "router_llm_selection",
            "pipeline_config", "widget_config",
            "created_at", "updated_at",
        } <= chatbot_cols

        n2m_cols = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("chatbot_knowledge_base")}
        )
        assert {"chatbot_id", "kb_id"} <= n2m_cols
    await engine.dispose()
