import pytest
from sqlalchemy import text

from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings


@pytest.mark.integration
async def test_engine_connects_to_postgres(settings: Settings) -> None:
    engine = build_engine(settings.postgres_url)
    session_factory = build_session_factory(engine)

    async with session_factory() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1

    await engine.dispose()
