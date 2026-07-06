import asyncio
import subprocess

import pytest
from sqlalchemy import inspect

from tfm_rag.infrastructure.persistence.engine import build_engine
from tfm_rag.infrastructure.settings import Settings


@pytest.mark.integration
async def test_migration_0014_adds_sources_description(settings: Settings) -> None:
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
            lambda sc: {c["name"]: c for c in inspect(sc).get_columns("sources")}
        )
    await engine.dispose()
    assert "description" in cols, "sources.description column missing after migration"
    assert cols["description"]["nullable"] is True
