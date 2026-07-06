"""Integration test for migration 0019 — eval_runs 'cancelled' status."""
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from tfm_rag.infrastructure.persistence.engine import build_engine
from tfm_rag.infrastructure.settings import Settings

pytestmark = pytest.mark.integration


async def _seed_tenant_and_chatbot(conn: AsyncConnection) -> tuple[UUID, UUID]:
    """Insert a throwaway tenant + chatbot to satisfy eval_runs' FKs.

    Only called when the DB has no chatbots at all (fresh/CI database). The
    caller is responsible for rolling back the enclosing transaction (or a
    savepoint around it) so nothing persists past the test.
    """
    tenant_id, chatbot_id = uuid4(), uuid4()
    await conn.execute(
        text(
            "INSERT INTO tenants (id, name, qdrant_collection_prefix, storage_prefix) "
            "VALUES (:id, :name, :prefix, :storage)"
        ),
        {
            "id": tenant_id,
            "name": f"migration-test-{tenant_id}",
            "prefix": f"kb_chunks__{tenant_id}",
            "storage": f"tenant_{tenant_id}/",
        },
    )
    await conn.execute(
        text(
            "INSERT INTO chatbots "
            "(id, tenant_id, name, system_prompt, llm_selection, pipeline_config, "
            "widget_config, public_key) "
            "VALUES (:id, :tenant_id, :name, :prompt, "
            "CAST(:llm AS JSONB), CAST(:pipeline AS JSONB), CAST(:widget AS JSONB), "
            ":public_key)"
        ),
        {
            "id": chatbot_id,
            "tenant_id": tenant_id,
            "name": "Migration Test Bot",
            "prompt": "You are a test bot.",
            "llm": "{}",
            "pipeline": '{"max_self_correction_retries": 0}',
            "widget": "{}",
            "public_key": f"migration-test-{chatbot_id}",
        },
    )
    return tenant_id, chatbot_id


@pytest.mark.asyncio
async def test_cancelled_status_in_check_constraint(settings: Settings) -> None:
    """The ck_eval_runs_status CHECK constraint must include 'cancelled'."""
    engine = build_engine(settings.postgres_url)
    async with engine.connect() as conn:
        row = await conn.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_eval_runs_status' "
                "AND conrelid = 'eval_runs'::regclass"
            )
        )
        assert row is not None, (
            "ck_eval_runs_status constraint not found — run alembic upgrade head"
        )
        assert "cancelled" in row, (
            f"'cancelled' not found in CHECK constraint: {row!r} — "
            "run alembic upgrade head (0019)"
        )
    await engine.dispose()


@pytest.mark.asyncio
async def test_cancelled_status_row_commits(settings: Settings) -> None:
    """A row with status='cancelled' must commit without violating the CHECK."""
    engine = build_engine(settings.postgres_url)
    async with engine.begin() as conn:
        # Everything below (including a seeded tenant/chatbot, if needed) is
        # rolled back to this savepoint before the transaction commits, so
        # the test is self-contained regardless of what's already in the DB.
        await conn.execute(text("SAVEPOINT sp_seed"))
        row = await conn.execute(
            text("SELECT tenant_id, id FROM chatbots LIMIT 1")
        )
        result = row.fetchone()
        if result is not None:
            tenant_id, chatbot_id = result[0], result[1]
        else:
            tenant_id, chatbot_id = await _seed_tenant_and_chatbot(conn)

        await conn.execute(text("SAVEPOINT sp_cancelled_test"))
        try:
            await conn.execute(
                text(
                    "INSERT INTO eval_runs "
                    "(id, tenant_id, chatbot_id, judge_model, status) "
                    "VALUES (gen_random_uuid(), :tid, :cid, 'test-model', 'cancelled')"
                ),
                {"tid": tenant_id, "cid": chatbot_id},
            )
        finally:
            await conn.execute(text("ROLLBACK TO SAVEPOINT sp_cancelled_test"))
        await conn.execute(text("ROLLBACK TO SAVEPOINT sp_seed"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_bogus_status_violates_check(settings: Settings) -> None:
    """A row with an invalid status must raise IntegrityError (CHECK violation)."""
    engine = build_engine(settings.postgres_url)
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            # A seeded tenant/chatbot (if needed) lives in the same
            # transaction as the failing insert below, so when the CHECK
            # violation raises, engine.begin() rolls back everything —
            # nothing is persisted regardless of prior DB state.
            row = await conn.execute(
                text("SELECT tenant_id, id FROM chatbots LIMIT 1")
            )
            result = row.fetchone()
            if result is not None:
                tenant_id, chatbot_id = result[0], result[1]
            else:
                tenant_id, chatbot_id = await _seed_tenant_and_chatbot(conn)

            await conn.execute(
                text(
                    "INSERT INTO eval_runs "
                    "(id, tenant_id, chatbot_id, judge_model, status) "
                    "VALUES (gen_random_uuid(), :tid, :cid, 'test-model', 'bogus_status')"
                ),
                {"tid": tenant_id, "cid": chatbot_id},
            )
    await engine.dispose()
