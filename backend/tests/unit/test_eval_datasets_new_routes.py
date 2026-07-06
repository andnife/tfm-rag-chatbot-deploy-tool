"""Unit tests for the new sql-seed and process routes in eval_datasets router.

Uses pure mocks — no live DB, no Qdrant, no MySQL.  Tests the route functions
directly, bypassing FastAPI's dependency injection.
"""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import (
    DatabaseConnectionError,
    SchemaIntrospectionError,
    UnsupportedDatabaseDialectError,
)
from tfm_rag.domain.value_objects.eval_dataset import EvalDatasetView
from tfm_rag.infrastructure.api.composition import get_storage
from tfm_rag.infrastructure.api.routers.eval_datasets import (
    EvalDatasetOut,
    SetSeedIn,
    process,
    upload_sql_seed,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.settings import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_view(ds_id=None, status="ready", db_schema_name="evalds_abc") -> EvalDatasetView:
    return EvalDatasetView(
        id=ds_id or uuid4(),
        tenant_id=uuid4(),
        name="Test DS",
        description=None,
        knowledge_base_id=uuid4(),
        db_schema_name=db_schema_name,
        sql_seed_artifact="storage://seed.sql",
        status=status,
        status_error=None,
        num_rows=0,
    )


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        postgres_url="postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag",
        qdrant_url="http://localhost:6333",
        ollama_base_url="http://localhost:11434",
        jwt_secret="x" * 32,
        fernet_key="qjd374RRcCpzdVhmmLHCnjxvBfrFwbwErhxIj4nq_XM=",
        storage_local_path="/tmp/test_storage",
    )


# ---------------------------------------------------------------------------
# get_storage composition provider
# ---------------------------------------------------------------------------

def test_get_storage_returns_local_storage() -> None:
    from tfm_rag.infrastructure.storage.local import LocalStorage
    store = get_storage(_settings())
    assert isinstance(store, LocalStorage)


# ---------------------------------------------------------------------------
# upload_sql_seed route
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_sql_seed_returns_200_on_success() -> None:
    ds_id = uuid4()
    view = _fake_view(ds_id=ds_id, status="draft", db_schema_name=None)
    body = SetSeedIn(sql="CREATE TABLE t (id INT);")
    ctx = RequestContext(tenant_id=uuid4())

    with patch(
        "tfm_rag.infrastructure.api.routers.eval_datasets.set_sql_seed",
        new=AsyncMock(return_value=view),
    ):
        result = await upload_sql_seed(
            ds_id, body, ctx,
            ds_repo=MagicMock(), item_repo=MagicMock(), storage=MagicMock(),
        )

    assert isinstance(result, EvalDatasetOut)
    assert result.id == str(ds_id)
    assert result.status == "draft"


@pytest.mark.asyncio
async def test_upload_sql_seed_raises_404_on_not_found() -> None:
    ds_id = uuid4()
    body = SetSeedIn(sql="CREATE TABLE t (id INT);")
    ctx = RequestContext(tenant_id=uuid4())

    with patch(
        "tfm_rag.infrastructure.api.routers.eval_datasets.set_sql_seed",
        new=AsyncMock(side_effect=NotFoundError("not found")),
    ):
        with pytest.raises(NotFoundError):
            await upload_sql_seed(
                ds_id, body, ctx,
                ds_repo=MagicMock(), item_repo=MagicMock(), storage=MagicMock(),
            )


# ---------------------------------------------------------------------------
# process route
# ---------------------------------------------------------------------------

def _process_deps() -> dict:
    return dict(
        ds_repo=MagicMock(),
        item_repo=MagicMock(),
        kb_repo=MagicMock(),
        sources_repo=MagicMock(),
        encryptor=MagicMock(),
        storage=MagicMock(),
        settings=_settings(),
    )


@pytest.mark.asyncio
async def test_process_returns_ready_view() -> None:
    ds_id = uuid4()
    view = _fake_view(ds_id=ds_id, status="ready", db_schema_name="evalds_abc")
    ctx = RequestContext(tenant_id=uuid4())

    with patch(
        "tfm_rag.infrastructure.api.routers.eval_datasets.process_dataset",
        new=AsyncMock(return_value=view),
    ):
        result = await process(ds_id, ctx, **_process_deps())

    assert isinstance(result, EvalDatasetOut)
    assert result.status == "ready"
    assert result.db_schema_name == "evalds_abc"


@pytest.mark.asyncio
async def test_process_raises_404_when_dataset_missing() -> None:
    ds_id = uuid4()
    ctx = RequestContext(tenant_id=uuid4())

    with patch(
        "tfm_rag.infrastructure.api.routers.eval_datasets.process_dataset",
        new=AsyncMock(side_effect=NotFoundError("no ds")),
    ):
        with pytest.raises(NotFoundError):
            await process(ds_id, ctx, **_process_deps())


@pytest.mark.asyncio
async def test_process_raises_400_on_db_connection_error() -> None:
    ds_id = uuid4()
    ctx = RequestContext(tenant_id=uuid4())

    with patch(
        "tfm_rag.infrastructure.api.routers.eval_datasets.process_dataset",
        new=AsyncMock(side_effect=DatabaseConnectionError("conn failed")),
    ):
        with pytest.raises(DatabaseConnectionError):
            await process(ds_id, ctx, **_process_deps())


@pytest.mark.asyncio
async def test_process_raises_400_on_schema_introspection_error() -> None:
    ds_id = uuid4()
    ctx = RequestContext(tenant_id=uuid4())

    with patch(
        "tfm_rag.infrastructure.api.routers.eval_datasets.process_dataset",
        new=AsyncMock(side_effect=SchemaIntrospectionError("introspect fail")),
    ):
        with pytest.raises(SchemaIntrospectionError):
            await process(ds_id, ctx, **_process_deps())


@pytest.mark.asyncio
async def test_process_raises_400_on_unsupported_dialect() -> None:
    ds_id = uuid4()
    ctx = RequestContext(tenant_id=uuid4())

    with patch(
        "tfm_rag.infrastructure.api.routers.eval_datasets.process_dataset",
        new=AsyncMock(side_effect=UnsupportedDatabaseDialectError("bad dialect")),
    ):
        with pytest.raises(UnsupportedDatabaseDialectError):
            await process(ds_id, ctx, **_process_deps())
