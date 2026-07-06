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
async def test_migration_0004_creates_kb_and_sources(settings: Settings) -> None:
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
            lambda sync_conn: inspect(sync_conn).get_table_names()
        )
        assert "knowledge_bases" in tables
        assert "sources" in tables
        kb_cols = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("knowledge_bases")}
        )
        assert {"id", "tenant_id", "name", "description",
                "chunking_config", "embedding_selection",
                "created_at", "updated_at"} <= kb_cols
        src_cols = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("sources")}
        )
        assert {"id", "kb_id", "type", "payload",
                "ingest_status", "last_ingest_at", "error"} <= src_cols
    await engine.dispose()
