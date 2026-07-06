"""Unit tests for purge_source_chunks (reindex_source use case)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from tfm_rag.application.knowledge.reindex_source import purge_source_chunks
from tfm_rag.domain.errors.knowledge import (
    KnowledgeBaseNotFoundError,
    SourceNotFoundError,
)

pytestmark = pytest.mark.asyncio

_TENANT_ID = uuid4()
_KB_ID = uuid4()
_SOURCE_ID = uuid4()


def _fake_kb(dim: int = 1024) -> SimpleNamespace:
    return SimpleNamespace(embedding_selection=SimpleNamespace(dim=dim))


class _FakeKbRepo:
    def __init__(self, kb: object | None) -> None:
        self._kb = kb
        self.get_calls: list[UUID] = []

    async def get_knowledge_base(self, kb_id: UUID) -> object:
        self.get_calls.append(kb_id)
        if self._kb is None:
            raise KnowledgeBaseNotFoundError(f"KB {kb_id} not found")
        return self._kb


class _FakeSrcRepo:
    def __init__(self, raises: Exception | None = None) -> None:
        self._raises = raises
        self.get_calls: list[tuple[UUID, UUID]] = []

    async def get_source(self, kb_id: UUID, source_id: UUID) -> None:
        self.get_calls.append((kb_id, source_id))
        if self._raises is not None:
            raise self._raises


def _make_qdrant() -> MagicMock:
    qdrant = MagicMock()
    qdrant.delete_by_source = AsyncMock()
    return qdrant


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_happy_path_calls_delete_by_source_with_correct_collection() -> None:
    kb_repo = _FakeKbRepo(_fake_kb(dim=1024))
    src_repo = _FakeSrcRepo()
    qdrant = _make_qdrant()

    await purge_source_chunks(
        kb_repo=kb_repo,
        sources_repo=src_repo,
        qdrant=qdrant,
        tenant_id=_TENANT_ID,
        kb_id=_KB_ID,
        source_id=_SOURCE_ID,
    )

    assert kb_repo.get_calls == [_KB_ID]
    assert src_repo.get_calls == [(_KB_ID, _SOURCE_ID)]

    qdrant.delete_by_source.assert_awaited_once()
    call_kwargs = qdrant.delete_by_source.await_args.kwargs
    assert call_kwargs["tenant_id"] == _TENANT_ID
    assert call_kwargs["source_id"] == _SOURCE_ID
    assert call_kwargs["collection"] == f"kb_chunks__{_TENANT_ID}__1024"


async def test_happy_path_collection_uses_dim_from_kb() -> None:
    kb_repo = _FakeKbRepo(_fake_kb(dim=768))
    qdrant = _make_qdrant()

    await purge_source_chunks(
        kb_repo=kb_repo,
        sources_repo=_FakeSrcRepo(),
        qdrant=qdrant,
        tenant_id=_TENANT_ID,
        kb_id=_KB_ID,
        source_id=_SOURCE_ID,
    )

    assert "__768" in qdrant.delete_by_source.await_args.kwargs["collection"]


# ---------------------------------------------------------------------------
# KB not found
# ---------------------------------------------------------------------------


async def test_kb_not_found_raises_kb_not_found_error() -> None:
    qdrant = _make_qdrant()

    with pytest.raises(KnowledgeBaseNotFoundError):
        await purge_source_chunks(
            kb_repo=_FakeKbRepo(None),
            sources_repo=_FakeSrcRepo(),
            qdrant=qdrant,
            tenant_id=_TENANT_ID,
            kb_id=_KB_ID,
            source_id=_SOURCE_ID,
        )

    qdrant.delete_by_source.assert_not_awaited()


async def test_kb_not_found_does_not_lookup_source() -> None:
    src_repo = _FakeSrcRepo()

    with pytest.raises(KnowledgeBaseNotFoundError):
        await purge_source_chunks(
            kb_repo=_FakeKbRepo(None),
            sources_repo=src_repo,
            qdrant=_make_qdrant(),
            tenant_id=_TENANT_ID,
            kb_id=_KB_ID,
            source_id=_SOURCE_ID,
        )

    assert src_repo.get_calls == []


# ---------------------------------------------------------------------------
# Source not found
# ---------------------------------------------------------------------------


async def test_source_not_found_raises_source_not_found_error() -> None:
    src_repo = _FakeSrcRepo(raises=SourceNotFoundError("src not found"))
    qdrant = _make_qdrant()

    with pytest.raises(SourceNotFoundError):
        await purge_source_chunks(
            kb_repo=_FakeKbRepo(_fake_kb()),
            sources_repo=src_repo,
            qdrant=qdrant,
            tenant_id=_TENANT_ID,
            kb_id=_KB_ID,
            source_id=_SOURCE_ID,
        )

    qdrant.delete_by_source.assert_not_awaited()


async def test_source_not_found_arbitrary_exception_wrapped() -> None:
    src_repo = _FakeSrcRepo(raises=RuntimeError("DB error"))

    with pytest.raises(SourceNotFoundError):
        await purge_source_chunks(
            kb_repo=_FakeKbRepo(_fake_kb()),
            sources_repo=src_repo,
            qdrant=_make_qdrant(),
            tenant_id=_TENANT_ID,
            kb_id=_KB_ID,
            source_id=_SOURCE_ID,
        )
