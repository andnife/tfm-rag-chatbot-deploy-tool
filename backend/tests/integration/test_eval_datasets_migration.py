import pytest
from sqlalchemy import text

from tfm_rag.infrastructure.persistence.engine import build_engine
from tfm_rag.infrastructure.settings import Settings

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_eval_datasets_tables_exist(settings: Settings) -> None:
    engine = build_engine(settings.postgres_url)
    async with engine.connect() as conn:
        for table in ("eval_datasets", "eval_dataset_rows"):
            exists = await conn.scalar(
                text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}
            )
            assert exists is not None, f"{table} missing — run alembic upgrade head"
    await engine.dispose()
