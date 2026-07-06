from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tfm_rag.infrastructure.persistence.models.eval_datasets import (
    EvalDatasetItemRow,
    EvalDatasetRow,
)
from tfm_rag.infrastructure.persistence.repositories.eval_datasets_repo import (
    EvalDatasetItemRepository,
    EvalDatasetRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext


def _ctx() -> RequestContext:
    return RequestContext(tenant_id=uuid4())


def _mock_session_scalar(value: Any) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


def test_repos_bind_to_models() -> None:
    assert EvalDatasetRepository.model is EvalDatasetRow
    assert EvalDatasetItemRepository.model is EvalDatasetItemRow


def test_item_repo_exposes_dataset_helpers() -> None:
    assert hasattr(EvalDatasetItemRepository, "list_for_dataset")
    assert hasattr(EvalDatasetItemRepository, "count_for_dataset")
    assert hasattr(EvalDatasetItemRepository, "delete_for_dataset")
    assert hasattr(EvalDatasetRepository, "find_by_name")


@pytest.mark.asyncio
async def test_find_by_name_returns_none_when_not_found() -> None:
    session = _mock_session_scalar(None)
    repo = EvalDatasetRepository(session, _ctx())
    result = await repo.find_by_name("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_find_by_name_returns_row_when_found() -> None:
    row = MagicMock(spec=EvalDatasetRow)
    session = _mock_session_scalar(row)
    repo = EvalDatasetRepository(session, _ctx())
    result = await repo.find_by_name("My DS")
    assert result is row


@pytest.mark.asyncio
async def test_list_for_dataset_returns_items() -> None:
    item = MagicMock(spec=EvalDatasetItemRow)
    result = MagicMock()
    result.scalars.return_value.all.return_value = [item]
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    repo = EvalDatasetItemRepository(session, _ctx())
    items = await repo.list_for_dataset(uuid4())
    assert items == [item]


@pytest.mark.asyncio
async def test_count_for_dataset_returns_integer() -> None:
    result = MagicMock()
    result.scalar_one.return_value = 7
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    repo = EvalDatasetItemRepository(session, _ctx())
    count = await repo.count_for_dataset(uuid4())
    assert count == 7


@pytest.mark.asyncio
async def test_delete_for_dataset_executes_without_error() -> None:
    session = MagicMock()
    session.execute = AsyncMock()
    repo = EvalDatasetItemRepository(session, _ctx())
    await repo.delete_for_dataset(uuid4())
    session.execute.assert_awaited_once()
