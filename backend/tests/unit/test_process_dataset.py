# backend/tests/unit/test_process_dataset.py
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tfm_rag.application.evaluation.manage_dataset import process_dataset
from tfm_rag.domain.entities.eval_dataset import EvalDataset


def _dataset(**over) -> EvalDataset:
    base = EvalDataset(
        id=over.get("id", uuid4()),
        tenant_id=over.get("tenant_id", uuid4()),
        name="ds",
        description=None,
        knowledge_base_id=over.get("knowledge_base_id", uuid4()),
        db_schema_name=None,
        sql_seed_artifact=over.get("sql_seed_artifact", "file:///seed.sql"),
        status="draft",
        status_error=None,
    )
    return base


@pytest.mark.asyncio
async def test_process_dataset_provisions_attaches_and_marks_ready() -> None:
    dataset = _dataset()
    ds_repo = MagicMock()
    ds_repo.get_dataset = AsyncMock(return_value=dataset)
    ds_repo.set_processing = AsyncMock()
    ds_repo.set_ready = AsyncMock(
        return_value=replace(dataset, status="ready", db_schema_name="evalds_abc")
    )
    ds_repo.set_failed = AsyncMock()
    item_repo = MagicMock()
    item_repo.count_for_dataset = AsyncMock(return_value=3)
    storage = MagicMock()
    storage.load = AsyncMock(return_value=b"CREATE TABLE t (id INT);")
    provisioner = AsyncMock(return_value="evalds_abc")
    attach_db = AsyncMock()

    view = await process_dataset(
        ds_repo=ds_repo,
        item_repo=item_repo,
        dataset_id=dataset.id,
        storage=storage,
        seed_provisioner=provisioner,
        attach_db=attach_db,
        mysql_cfg={"host": "h", "port": 3306, "admin_user": "root", "admin_password": "pw"},
    )
    provisioner.assert_awaited_once()
    attach_db.assert_awaited_once()
    ds_repo.set_processing.assert_awaited_once()
    ds_repo.set_ready.assert_awaited_once()
    assert ds_repo.set_ready.await_args.kwargs["db_schema_name"] == "evalds_abc"
    assert view.status == "ready"
    assert view.db_schema_name == "evalds_abc"
    assert view.num_rows == 3


@pytest.mark.asyncio
async def test_process_dataset_marks_failed_and_reraises_on_error() -> None:
    dataset = _dataset()
    ds_repo = MagicMock()
    ds_repo.get_dataset = AsyncMock(return_value=dataset)
    ds_repo.set_processing = AsyncMock()
    ds_repo.set_ready = AsyncMock()
    ds_repo.set_failed = AsyncMock()
    item_repo = MagicMock()
    item_repo.count_for_dataset = AsyncMock(return_value=0)
    storage = MagicMock()
    storage.load = AsyncMock(return_value=b"CREATE TABLE t (id INT);")
    provisioner = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        await process_dataset(
            ds_repo=ds_repo,
            item_repo=item_repo,
            dataset_id=dataset.id,
            storage=storage,
            seed_provisioner=provisioner,
            attach_db=AsyncMock(),
            mysql_cfg={"host": "h", "port": 3306, "admin_user": "root", "admin_password": "pw"},
        )
    ds_repo.set_failed.assert_awaited_once()
    assert "boom" in ds_repo.set_failed.await_args.kwargs["error"]
    ds_repo.set_ready.assert_not_awaited()
