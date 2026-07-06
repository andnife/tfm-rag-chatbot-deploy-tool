from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from tfm_rag.application.knowledge.create_knowledge_base import (
    create_knowledge_base,
)
from tfm_rag.application.knowledge.delete_knowledge_base import (
    delete_knowledge_base,
)
from tfm_rag.application.knowledge.detach_source import detach_source
from tfm_rag.application.knowledge.list_knowledge_bases import (
    list_knowledge_bases,
)
from tfm_rag.application.knowledge.list_sources import list_sources
from tfm_rag.application.knowledge.test_source_connection import (
    test_source_connection,
)
from tfm_rag.application.knowledge.update_knowledge_base import (
    update_knowledge_base,
)
from tfm_rag.domain.entities.knowledge_base import KnowledgeBase
from tfm_rag.domain.errors.common import NotFoundError, ValidationError
from tfm_rag.domain.errors.knowledge import (
    KnowledgeBaseInUseError,
    KnowledgeBaseNotFoundError,
    SourceNotFoundError,
)
from tfm_rag.domain.ports.source_connection_tester import (
    SOURCE_CONNECTION_TESTERS,
    SourceConnectionTestResult,
)
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.model_ref import ModelRef

_NOW = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)


def _tenant() -> UUID:
    return uuid4()


def _selection(credential_id: UUID | None = None) -> EmbeddingSelection:
    return EmbeddingSelection(
        credential_id=credential_id or uuid4(),
        model_id="bge-m3",
        dim=1024,
    )


def _kb_entity(
    *,
    name: str = "docs",
    description: str | None = None,
    chunking_config: ChunkingConfig | None = None,
    embedding_selection: EmbeddingSelection | None = None,
    description_llm: ModelRef | None = None,
    kb_id: UUID | None = None,
    tenant_id: UUID | None = None,
) -> KnowledgeBase:
    return KnowledgeBase(
        id=kb_id or uuid4(),
        tenant_id=tenant_id or uuid4(),
        name=name,
        description=description,
        chunking_config=chunking_config or ChunkingConfig.default(),
        embedding_selection=embedding_selection or _selection(),
        created_at=_NOW,
        updated_at=_NOW,
        description_llm=description_llm,
    )


# ---------------------------------------------------------------------------
# create_knowledge_base
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_knowledge_base_ensures_qdrant_and_persists() -> None:
    tenant_id = _tenant()
    qdrant = MagicMock()
    qdrant.ensure_collection = AsyncMock(return_value="kb_chunks__t__1024")
    repo = MagicMock()
    repo.find_by_name = AsyncMock(return_value=None)
    repo.create_knowledge_base = AsyncMock(
        side_effect=lambda **kw: _kb_entity(tenant_id=tenant_id, **kw)
    )
    selection = _selection()

    result = await create_knowledge_base(
        kb_repo=repo,
        qdrant=qdrant,
        tenant_id=tenant_id,
        name="docs",
        description="manuals",
        chunking_config=ChunkingConfig.default(),
        embedding_selection=selection,
    )

    qdrant.ensure_collection.assert_awaited_once_with(tenant_id, 1024)
    repo.create_knowledge_base.assert_awaited_once()
    assert result.name == "docs"
    assert result.embedding_selection.dim == 1024


@pytest.mark.asyncio
async def test_create_knowledge_base_rejects_duplicate_name() -> None:
    tenant_id = _tenant()
    qdrant = MagicMock()
    qdrant.ensure_collection = AsyncMock()
    repo = MagicMock()
    repo.find_by_name = AsyncMock(return_value=_kb_entity())

    with pytest.raises(ValidationError, match="already exists"):
        await create_knowledge_base(
            kb_repo=repo,
            qdrant=qdrant,
            tenant_id=tenant_id,
            name="docs",
            description=None,
            chunking_config=ChunkingConfig.default(),
            embedding_selection=_selection(),
        )

    qdrant.ensure_collection.assert_not_called()


@pytest.mark.asyncio
async def test_create_knowledge_base_with_description_llm_stores_it() -> None:
    tenant_id = _tenant()
    qdrant = MagicMock()
    qdrant.ensure_collection = AsyncMock(return_value="kb_chunks__t__1024")
    repo = MagicMock()
    repo.find_by_name = AsyncMock(return_value=None)
    repo.create_knowledge_base = AsyncMock(
        side_effect=lambda **kw: _kb_entity(tenant_id=tenant_id, **kw)
    )
    desc_llm = ModelRef(credential_id=uuid4(), model_id="gpt-4o-mini")

    result = await create_knowledge_base(
        kb_repo=repo,
        qdrant=qdrant,
        tenant_id=tenant_id,
        name="docs",
        description="manuals",
        chunking_config=ChunkingConfig.default(),
        embedding_selection=_selection(),
        description_llm=desc_llm,
    )

    assert result.description_llm == desc_llm


@pytest.mark.asyncio
async def test_create_knowledge_base_without_description_llm_stores_none() -> None:
    tenant_id = _tenant()
    qdrant = MagicMock()
    qdrant.ensure_collection = AsyncMock(return_value="kb_chunks__t__1024")
    repo = MagicMock()
    repo.find_by_name = AsyncMock(return_value=None)
    repo.create_knowledge_base = AsyncMock(
        side_effect=lambda **kw: _kb_entity(tenant_id=tenant_id, **kw)
    )

    result = await create_knowledge_base(
        kb_repo=repo,
        qdrant=qdrant,
        tenant_id=tenant_id,
        name="docs",
        description="manuals",
        chunking_config=ChunkingConfig.default(),
        embedding_selection=_selection(),
    )

    assert result.description_llm is None


# ---------------------------------------------------------------------------
# update_knowledge_base
# ---------------------------------------------------------------------------


def _update_repo(existing: KnowledgeBase) -> MagicMock:
    repo = MagicMock()
    repo.get_knowledge_base = AsyncMock(return_value=existing)
    repo.update_knowledge_base = AsyncMock(
        side_effect=lambda kb_id, **kw: _kb_entity(kb_id=kb_id, **kw)
    )
    return repo


@pytest.mark.asyncio
async def test_update_knowledge_base_flags_reindex_when_embedding_changes() -> None:
    tenant_id = _tenant()
    old_selection = _selection()
    new_selection = EmbeddingSelection(
        credential_id=old_selection.credential_id,
        model_id="nomic-embed-text",
        dim=768,
    )
    existing = _kb_entity(
        embedding_selection=old_selection, tenant_id=tenant_id, name="docs"
    )
    repo = _update_repo(existing)
    qdrant = MagicMock()
    qdrant.ensure_collection = AsyncMock(return_value="kb_chunks__t__768")

    result = await update_knowledge_base(
        kb_repo=repo,
        qdrant=qdrant,
        tenant_id=tenant_id,
        kb_id=existing.id,
        name=None,
        description=None,
        chunking_config=None,
        embedding_selection=new_selection,
    )

    assert result.reindex_required is True
    qdrant.ensure_collection.assert_awaited_once_with(tenant_id, 768)


@pytest.mark.asyncio
async def test_update_knowledge_base_no_reindex_when_only_name_changes() -> None:
    tenant_id = _tenant()
    existing = _kb_entity(name="old", tenant_id=tenant_id)
    repo = _update_repo(existing)
    qdrant = MagicMock()
    qdrant.ensure_collection = AsyncMock()

    result = await update_knowledge_base(
        kb_repo=repo,
        qdrant=qdrant,
        tenant_id=tenant_id,
        kb_id=existing.id,
        name="new",
        description=None,
        chunking_config=None,
        embedding_selection=None,
    )

    assert result.reindex_required is False
    qdrant.ensure_collection.assert_not_called()
    assert repo.update_knowledge_base.await_args.kwargs["name"] == "new"


@pytest.mark.asyncio
async def test_update_knowledge_base_sets_description_llm() -> None:
    tenant_id = _tenant()
    existing = _kb_entity(name="docs", tenant_id=tenant_id, description_llm=None)
    repo = _update_repo(existing)
    qdrant = MagicMock()
    desc_llm = ModelRef(credential_id=uuid4(), model_id="gpt-4o-mini")

    result = await update_knowledge_base(
        kb_repo=repo,
        qdrant=qdrant,
        tenant_id=tenant_id,
        kb_id=existing.id,
        name=None,
        description=None,
        chunking_config=None,
        embedding_selection=None,
        description_llm=desc_llm,
    )

    assert repo.update_knowledge_base.await_args.kwargs["description_llm"] == desc_llm
    assert result.kb.description_llm == desc_llm


@pytest.mark.asyncio
async def test_update_knowledge_base_clears_description_llm_when_explicit_none() -> None:
    tenant_id = _tenant()
    existing = _kb_entity(
        name="docs",
        tenant_id=tenant_id,
        description_llm=ModelRef(credential_id=uuid4(), model_id="gpt-4o-mini"),
    )
    repo = _update_repo(existing)
    qdrant = MagicMock()

    result = await update_knowledge_base(
        kb_repo=repo,
        qdrant=qdrant,
        tenant_id=tenant_id,
        kb_id=existing.id,
        name=None,
        description=None,
        chunking_config=None,
        embedding_selection=None,
        description_llm=None,
    )

    assert repo.update_knowledge_base.await_args.kwargs["description_llm"] is None
    assert result.kb.description_llm is None


@pytest.mark.asyncio
async def test_update_knowledge_base_leaves_description_llm_untouched_when_not_provided() -> None:
    """Omitting description_llm entirely (the _UNSET default) must not touch
    the existing value."""
    tenant_id = _tenant()
    original = ModelRef(credential_id=uuid4(), model_id="gpt-4o-mini")
    existing = _kb_entity(name="docs", tenant_id=tenant_id, description_llm=original)
    repo = _update_repo(existing)
    qdrant = MagicMock()

    result = await update_knowledge_base(
        kb_repo=repo,
        qdrant=qdrant,
        tenant_id=tenant_id,
        kb_id=existing.id,
        name="renamed",
        description=None,
        chunking_config=None,
        embedding_selection=None,
        # description_llm omitted -> defaults to _UNSET -> no change
    )

    assert repo.update_knowledge_base.await_args.kwargs["description_llm"] == original
    assert result.kb.description_llm == original


@pytest.mark.asyncio
async def test_update_knowledge_base_raises_when_missing() -> None:
    repo = MagicMock()
    repo.get_knowledge_base = AsyncMock(side_effect=NotFoundError("nope"))

    with pytest.raises(KnowledgeBaseNotFoundError):
        await update_knowledge_base(
            kb_repo=repo,
            qdrant=MagicMock(),
            tenant_id=_tenant(),
            kb_id=uuid4(),
            name="x",
            description=None,
            chunking_config=None,
            embedding_selection=None,
        )


# ---------------------------------------------------------------------------
# list_knowledge_bases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_knowledge_bases_uses_pagination() -> None:
    repo = MagicMock()
    repo.list_knowledge_bases = AsyncMock(return_value=[])

    await list_knowledge_bases(kb_repo=repo, limit=5, offset=10)

    repo.list_knowledge_bases.assert_awaited_once_with(limit=5, offset=10)


# ---------------------------------------------------------------------------
# delete_knowledge_base
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_knowledge_base_calls_repo() -> None:
    tenant_id = _tenant()
    repo = MagicMock()
    repo.delete_knowledge_base = AsyncMock()
    kb_id = uuid4()

    await delete_knowledge_base(
        kb_repo=repo,
        sources_repo=MagicMock(),
        tenant_id=tenant_id,
        kb_id=kb_id,
    )

    repo.delete_knowledge_base.assert_awaited_once_with(kb_id)


@pytest.mark.asyncio
async def test_delete_knowledge_base_cleans_qdrant_and_storage() -> None:
    """Deleting a KB purges its Qdrant chunks AND storage files for every
    source, after the SQL delete commits."""
    tenant_id = _tenant()
    kb = _kb_entity(embedding_selection=_selection(), tenant_id=tenant_id)
    repo = MagicMock()
    repo.get_knowledge_base = AsyncMock(return_value=kb)
    repo.delete_knowledge_base = AsyncMock()

    doc = SimpleNamespace(
        id=uuid4(), type="document", payload={"storage_uri": "file:///data/doc.pdf"}
    )
    db = SimpleNamespace(id=uuid4(), type="database", payload={"host": "x"})
    src_repo = MagicMock()
    src_repo.list_sources_by_kb = AsyncMock(return_value=[doc, db])

    qdrant = MagicMock()
    qdrant.delete_by_source = AsyncMock()
    storage = MagicMock()
    storage.delete = AsyncMock()

    kb_id = uuid4()
    await delete_knowledge_base(
        kb_repo=repo,
        sources_repo=src_repo,
        tenant_id=tenant_id,
        qdrant=qdrant,
        storage=storage,
        kb_id=kb_id,
    )

    repo.delete_knowledge_base.assert_awaited_once_with(kb_id)
    assert qdrant.delete_by_source.await_count == 2
    storage.delete.assert_awaited_once_with("file:///data/doc.pdf")


@pytest.mark.asyncio
async def test_delete_knowledge_base_in_use_skips_cleanup() -> None:
    """If the KB is referenced by a chatbot the SQL delete raises and we must
    NOT have purged Qdrant/storage — the KB still exists."""
    tenant_id = _tenant()
    kb = _kb_entity(embedding_selection=_selection(), tenant_id=tenant_id)
    repo = MagicMock()
    repo.get_knowledge_base = AsyncMock(return_value=kb)
    repo.delete_knowledge_base = AsyncMock(
        side_effect=KnowledgeBaseInUseError("in use")
    )

    doc = SimpleNamespace(
        id=uuid4(), type="document", payload={"storage_uri": "file:///data/doc.pdf"}
    )
    src_repo = MagicMock()
    src_repo.list_sources_by_kb = AsyncMock(return_value=[doc])

    qdrant = MagicMock()
    qdrant.delete_by_source = AsyncMock()
    storage = MagicMock()
    storage.delete = AsyncMock()

    with pytest.raises(KnowledgeBaseInUseError):
        await delete_knowledge_base(
            kb_repo=repo,
            sources_repo=src_repo,
            tenant_id=tenant_id,
            qdrant=qdrant,
            storage=storage,
            kb_id=uuid4(),
        )

    qdrant.delete_by_source.assert_not_awaited()
    storage.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_knowledge_base_propagates_kb_in_use() -> None:
    """The repo maps the FK violation to KnowledgeBaseInUseError; the use case
    propagates it unchanged (no cleanup wiring)."""
    repo = MagicMock()
    repo.delete_knowledge_base = AsyncMock(
        side_effect=KnowledgeBaseInUseError("referenced")
    )

    with pytest.raises(KnowledgeBaseInUseError):
        await delete_knowledge_base(
            kb_repo=repo,
            sources_repo=MagicMock(),
            tenant_id=_tenant(),
            kb_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# detach_source
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detach_source_deletes_storage_file() -> None:
    tenant_id = _tenant()
    kb = _kb_entity(tenant_id=tenant_id)
    kb_repo = MagicMock()
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb)

    src = SimpleNamespace(
        type="document", payload={"storage_uri": "file:///data/doc.pdf"}
    )
    src_repo = MagicMock()
    src_repo.get_source = AsyncMock(return_value=src)
    src_repo.delete_source = AsyncMock()

    storage = MagicMock()
    storage.delete = AsyncMock()

    source_id = uuid4()
    await detach_source(
        kb_repo=kb_repo,
        sources_repo=src_repo,
        tenant_id=tenant_id,
        storage=storage,
        kb_id=kb.id,
        source_id=source_id,
    )

    storage.delete.assert_awaited_once_with("file:///data/doc.pdf")
    src_repo.delete_source.assert_awaited_once_with(kb.id, source_id)


@pytest.mark.asyncio
async def test_detach_source_validates_kb_and_deletes() -> None:
    tenant_id = _tenant()
    kb = _kb_entity(tenant_id=tenant_id)
    kb_repo = MagicMock()
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb)
    src_repo = MagicMock()
    src_repo.delete_source = AsyncMock()
    source_id = uuid4()

    await detach_source(
        kb_repo=kb_repo,
        sources_repo=src_repo,
        tenant_id=tenant_id,
        kb_id=kb.id,
        source_id=source_id,
    )

    src_repo.delete_source.assert_awaited_once_with(kb.id, source_id)


@pytest.mark.asyncio
async def test_detach_source_raises_when_source_missing() -> None:
    tenant_id = _tenant()
    kb = _kb_entity(tenant_id=tenant_id)
    kb_repo = MagicMock()
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb)
    src_repo = MagicMock()
    src_repo.delete_source = AsyncMock(side_effect=SourceNotFoundError("nope"))

    with pytest.raises(SourceNotFoundError):
        await detach_source(
            kb_repo=kb_repo,
            sources_repo=src_repo,
            tenant_id=tenant_id,
            kb_id=kb.id,
            source_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_detach_source_with_qdrant_deletes_chunks() -> None:
    """When qdrant is provided, chunks are deleted for the KB's embedding dim."""
    tenant_id = _tenant()
    kb = _kb_entity(embedding_selection=_selection(), tenant_id=tenant_id)
    kb_repo = MagicMock()
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb)
    src_repo = MagicMock()
    src_repo.delete_source = AsyncMock()
    qdrant = MagicMock()
    qdrant.delete_by_source = AsyncMock()
    source_id = uuid4()

    await detach_source(
        kb_repo=kb_repo,
        sources_repo=src_repo,
        tenant_id=tenant_id,
        qdrant=qdrant,
        kb_id=uuid4(),
        source_id=source_id,
    )

    qdrant.delete_by_source.assert_awaited_once()
    call_kwargs = qdrant.delete_by_source.await_args.kwargs
    assert call_kwargs["source_id"] == source_id
    assert "__1024" in call_kwargs["collection"]


# ---------------------------------------------------------------------------
# list_sources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sources_loads_kb_then_lists() -> None:
    kb_repo = MagicMock()
    kb_repo.get_knowledge_base = AsyncMock(return_value=_kb_entity())
    src_repo = MagicMock()
    src_repo.list_sources_by_kb = AsyncMock(return_value=[])
    kb_id = uuid4()

    result = await list_sources(
        kb_repo=kb_repo, sources_repo=src_repo, kb_id=kb_id
    )

    kb_repo.get_knowledge_base.assert_awaited_once_with(kb_id)
    src_repo.list_sources_by_kb.assert_awaited_once_with(kb_id)
    assert result == []


@pytest.mark.asyncio
async def test_list_sources_raises_when_kb_missing() -> None:
    kb_repo = MagicMock()
    kb_repo.get_knowledge_base = AsyncMock(side_effect=NotFoundError("nope"))
    src_repo = MagicMock()

    with pytest.raises(KnowledgeBaseNotFoundError):
        await list_sources(
            kb_repo=kb_repo, sources_repo=src_repo, kb_id=uuid4()
        )


# ---------------------------------------------------------------------------
# test_source_connection (unchanged — stateless, no repos)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_source_connection_returns_not_registered_when_no_tester() -> None:
    SOURCE_CONNECTION_TESTERS.clear()

    result = await test_source_connection(
        spec_type="document",
        spec={"kind": "cloud", "cloud_folder_ref": "x"},
    )

    assert result.ok is False
    assert result.error is not None
    assert "TESTER_NOT_REGISTERED" in result.error


@pytest.mark.asyncio
async def test_test_source_connection_invokes_registered_tester() -> None:
    captured: dict[str, Any] = {}

    class FakeTester:
        async def test(self, spec: dict[str, Any]) -> SourceConnectionTestResult:
            captured["spec"] = spec
            return SourceConnectionTestResult(ok=True, error=None)

    SOURCE_CONNECTION_TESTERS["database"] = FakeTester()
    try:
        result = await test_source_connection(
            spec_type="database",
            spec={"driver": "postgres", "host": "x"},
        )
    finally:
        del SOURCE_CONNECTION_TESTERS["database"]

    assert result.ok is True
    assert captured["spec"]["driver"] == "postgres"
