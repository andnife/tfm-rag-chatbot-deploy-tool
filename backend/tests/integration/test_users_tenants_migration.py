import asyncio
import subprocess

import pytest
from sqlalchemy import inspect, text

from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings


@pytest.mark.integration
async def test_migration_0002_creates_tables(settings: Settings) -> None:
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
    factory = build_session_factory(engine)
    async with factory() as session:
        v = (await session.execute(
            text("SELECT version_num FROM alembic_version")
        )).scalar()
        # 0002 introduces the tables; later migrations may bump the head.
        # Verify the table side-effect, not a frozen revision number.
        assert v is not None
        async with engine.connect() as conn:
            tables = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names()
            )
            assert "tenants" in tables
            assert "users" in tables
    await engine.dispose()
