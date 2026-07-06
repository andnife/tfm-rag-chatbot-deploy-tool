# backend/tests/unit/test_manage_dataset.py
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tfm_rag.application.evaluation.manage_dataset import (
    create_eval_dataset,
    delete_eval_dataset,
    replace_dataset_rows,
    set_sql_seed,
)
from tfm_rag.domain.entities.eval_dataset import EvalDataset
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.errors.evaluation import EvalDatasetError
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection


def _selection() -> EmbeddingSelection:
    return EmbeddingSelection(credential_id=uuid4(), model_id="bge-m3", dim=1024)


def _dataset(**over) -> EvalDataset:
    return EvalDataset(
        id=over.get("id", uuid4()),
        tenant_id=over.get("tenant_id", uuid4()),
        name=over.get("name", "ds"),
        description=over.get("description"),
        knowledge_base_id=over.get("knowledge_base_id", uuid4()),
        db_schema_name=over.get("db_schema_name"),
        sql_seed_artifact=over.get("sql_seed_artifact"),
        status=over.get("status", "draft"),
        status_error=over.get("status_error"),
    )


@pytest.mark.asyncio
async def test_create_eval_dataset_mints_kb_and_persists_draft() -> None:
    tenant_id = uuid4()
    kb_id = uuid4()
    kb_view = MagicMock()
    kb_view.id = kb_id
    kb_creator = AsyncMock(return_value=kb_view)

    dataset = _dataset(tenant_id=tenant_id, knowledge_base_id=kb_id, status="draft")
    ds_repo = MagicMock()
    ds_repo.find_dataset_by_name = AsyncMock(return_value=None)
    ds_repo.create_dataset = AsyncMock(return_value=dataset)

    result = await create_eval_dataset(
        ds_repo=ds_repo,
        kb_repo=MagicMock(),
        qdrant=MagicMock(),
        tenant_id=tenant_id,
        kb_creator=kb_creator,
        name="Garantías",
        description="suite de prueba",
        chunking_config=ChunkingConfig.default(),
        embedding_selection=_selection(),
    )

    kb_creator.assert_awaited_once()
    assert result.knowledge_base_id == kb_id
    assert result.status == "draft"
    assert result.num_rows == 0
    ds_repo.create_dataset.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_eval_dataset_rejects_duplicate_name() -> None:
    ds_repo = MagicMock()
    ds_repo.find_dataset_by_name = AsyncMock(return_value=_dataset())

    with pytest.raises(ValidationError):
        await create_eval_dataset(
            ds_repo=ds_repo,
            kb_repo=MagicMock(),
            qdrant=MagicMock(),
            tenant_id=uuid4(),
            kb_creator=AsyncMock(),
            name="dup",
            description=None,
            chunking_config=ChunkingConfig.default(),
            embedding_selection=_selection(),
        )


@pytest.mark.asyncio
async def test_delete_eval_dataset_cascades_kb() -> None:
    tenant_id = uuid4()
    kb_id = uuid4()
    dataset = _dataset(tenant_id=tenant_id, knowledge_base_id=kb_id)
    ds_repo = MagicMock()
    ds_repo.get_dataset = AsyncMock(return_value=dataset)
    ds_repo.delete_dataset = AsyncMock()
    kb_deleter = AsyncMock()

    await delete_eval_dataset(
        ds_repo=ds_repo,
        kb_repo=MagicMock(),
        sources_repo=MagicMock(),
        qdrant=MagicMock(),
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        kb_deleter=kb_deleter,
    )

    kb_deleter.assert_awaited_once()
    call = kb_deleter.await_args
    assert call.kwargs["kb_id"] == kb_id
    assert call.kwargs["tenant_id"] == tenant_id
    assert "kb_repo" in call.kwargs and "sources_repo" in call.kwargs
    ds_repo.delete_dataset.assert_awaited_once()


@pytest.mark.asyncio
async def test_replace_dataset_rows_validates_and_inserts() -> None:
    dataset = _dataset()
    ds_repo = MagicMock()
    ds_repo.get_dataset = AsyncMock(return_value=dataset)
    item_repo = MagicMock()
    item_repo.replace_dataset_rows = AsyncMock()
    item_repo.count_for_dataset = AsyncMock(return_value=1)

    view = await replace_dataset_rows(
        ds_repo=ds_repo,
        item_repo=item_repo,
        dataset_id=dataset.id,
        parsed_rows=[{
            "question": "¿Cuántos años de garantía?", "ground_truth": "3 años",
            "scenario": "doc_only", "complexity": "factual",
        }],
    )
    item_repo.replace_dataset_rows.assert_awaited_once()
    # one validated item passed to the repo
    inserted = item_repo.replace_dataset_rows.await_args.args[1]
    assert len(inserted) == 1
    assert inserted[0].question == "¿Cuántos años de garantía?"
    assert view.num_rows == 1


@pytest.mark.asyncio
async def test_replace_dataset_rows_rejects_bad_row() -> None:
    dataset = _dataset()
    ds_repo = MagicMock()
    ds_repo.get_dataset = AsyncMock(return_value=dataset)
    item_repo = MagicMock()
    item_repo.replace_dataset_rows = AsyncMock()

    with pytest.raises(EvalDatasetError):
        await replace_dataset_rows(
            ds_repo=ds_repo,
            item_repo=item_repo,
            dataset_id=dataset.id,
            parsed_rows=[{"question": "x", "ground_truth": "", "scenario": "doc_only",
                          "complexity": "factual"}],
        )
    # All-or-nothing guarantee: validation must fire BEFORE any repo mutation.
    item_repo.replace_dataset_rows.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_sql_seed_stores_artifact_and_records_uri() -> None:
    tenant_id = uuid4()
    dataset = _dataset(tenant_id=tenant_id, status="draft")
    ds_repo = MagicMock()
    ds_repo.get_dataset = AsyncMock(return_value=dataset)
    ds_repo.set_sql_seed_artifact = AsyncMock(
        return_value=replace(dataset, sql_seed_artifact="file:///x/seed.sql")
    )
    item_repo = MagicMock()
    item_repo.count_for_dataset = AsyncMock(return_value=0)
    storage = MagicMock()
    storage.save = AsyncMock(return_value="file:///x/seed.sql")

    view = await set_sql_seed(
        ds_repo=ds_repo,
        item_repo=item_repo,
        dataset_id=dataset.id,
        seed_bytes=b"CREATE TABLE t (id INT);",
        storage=storage,
        tenant_id=tenant_id,
    )
    storage.save.assert_awaited_once()
    ds_repo.set_sql_seed_artifact.assert_awaited_once()
    assert ds_repo.set_sql_seed_artifact.await_args.kwargs["uri"] == "file:///x/seed.sql"
    assert view.status == "draft"
