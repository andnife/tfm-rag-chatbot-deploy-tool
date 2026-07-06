"""Integration test for migration 0017 — eval_runs dataset_id + token/cost columns."""
import pytest
from sqlalchemy import text

from tfm_rag.infrastructure.persistence.engine import build_engine
from tfm_rag.infrastructure.settings import Settings

pytestmark = pytest.mark.integration

EXPECTED_COLUMNS = {
    "dataset_id",
    "tokens_gen_in",
    "tokens_gen_out",
    "tokens_judge_in",
    "tokens_judge_out",
}


@pytest.mark.asyncio
async def test_eval_runs_0017_columns_exist(settings: Settings) -> None:
    engine = build_engine(settings.postgres_url)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='eval_runs'"
            )
        )
        existing = {row[0] for row in rows}
        missing = EXPECTED_COLUMNS - existing
        assert not missing, f"Columns missing from eval_runs: {missing} — run alembic upgrade head"


@pytest.mark.asyncio
async def test_eval_runs_dataset_path_nullable(settings: Settings) -> None:
    engine = build_engine(settings.postgres_url)
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='eval_runs' "
                "AND column_name='dataset_path'"
            )
        )
        result = row.fetchone()
        assert result is not None, "dataset_path column not found"
        assert result[0] == "YES", "dataset_path should be NULLABLE after migration 0017"

    await engine.dispose()
