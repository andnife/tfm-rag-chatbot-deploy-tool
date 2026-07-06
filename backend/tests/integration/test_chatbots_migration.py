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
            "system_prompt", "llm_selection",
            "pipeline_config", "widget_config",
            "created_at", "updated_at",
        } <= chatbot_cols

        n2m_cols = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("chatbot_knowledge_base")}
        )
        assert {"chatbot_id", "kb_id"} <= n2m_cols
    await engine.dispose()


@pytest.mark.integration
async def test_migration_0012_adds_role_llm_selections(settings: Settings) -> None:
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
        cols = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("chatbots")}
        )
        assert "role_llm_selections" in cols
    await engine.dispose()


@pytest.mark.integration
async def test_migration_0013_swaps_pipeline_check_and_rewrites_rows(
    settings: Settings,
) -> None:
    result = await asyncio.to_thread(
        subprocess.run, ["alembic", "upgrade", "head"],
        cwd=".", capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr

    engine = build_engine(settings.postgres_url)
    build_session_factory(engine)
    async with engine.connect() as conn:
        checks = await conn.run_sync(
            lambda sc: {
                c["name"]
                for c in inspect(sc).get_check_constraints("chatbots")
            }
        )
        assert "ck_chatbots_max_self_correction_retries" in checks
        assert "ck_chatbots_max_retrieval_iterations" not in checks
    await engine.dispose()
