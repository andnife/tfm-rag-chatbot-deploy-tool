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
async def test_migration_0005_creates_ingestion_jobs(settings: Settings) -> None:
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
        assert "ingestion_jobs" in tables
        cols = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("ingestion_jobs")}
        )
        assert {
            "id", "source_id", "tenant_id", "status",
            "progress", "error", "started_at", "finished_at",
        } <= cols
    await engine.dispose()


@pytest.mark.integration
async def test_migration_0015_adds_stage_and_item_counters(
    settings: Settings,
) -> None:
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
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sc: {
                c["name"]: c for c in inspect(sc).get_columns("ingestion_jobs")
            }
        )
    await engine.dispose()
    for name in ("stage", "items_done", "items_total"):
        assert name in cols, f"ingestion_jobs.{name} missing after migration 0015"
        assert cols[name]["nullable"] is True
