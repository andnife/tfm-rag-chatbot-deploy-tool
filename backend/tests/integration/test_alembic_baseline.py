import asyncio
import subprocess

import pytest
from sqlalchemy import text

from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings


@pytest.mark.integration
async def test_alembic_baseline_marks_db(settings: Settings) -> None:
    # Run migrations up to head
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
    session_factory = build_session_factory(engine)
    async with session_factory() as session:
        result = await session.execute(
            text("SELECT version_num FROM alembic_version")
        )
        version = result.scalar()
        assert version == "0001"
    await engine.dispose()
