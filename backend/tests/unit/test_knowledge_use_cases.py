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
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.errors.knowledge import (
    KnowledgeBaseNotFoundError,
    SourceNotFoundError,
)
from tfm_rag.domain.ports.source_connection_tester import (
    SOURCE_CONNECTION_TESTERS,
    SourceConnectionTestResult,
)
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.infrastructure.persistence.repository import RequestContext


def _ctx() -> RequestContext:
    return RequestContext(tenant_id=uuid4(), user_id=uuid4())


def _selection(credential_id: UUID | None = None) -> EmbeddingSelection:
    return EmbeddingSelection(
        provider_id="ollama",
        credential_id=credential_id or uuid4(),
        model_id="bge-m3",
        dim=1024,
    )


@pytest.mark.asyncio
async def test_create_knowledge_base_ensures_qdrant_and_persists() -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    ctx = _ctx()
    qdrant = MagicMock()
    qdrant.ensure_collection = AsyncMock(return_value="kb_chunks__t__1024")
    repo = MagicMock()
    repo.find_by_name = AsyncMock(return_value=None)
    repo.add = AsyncMock(side_effect=lambda r: r)
    selection = _selection()

    result = await create_knowledge_base(
        session,
        ctx,
        qdrant,
        repo_factory=lambda s, c: repo,
        name="docs",
        description="manuals",
        chunking_config=ChunkingConfig.default(),
        embedding_selection=selection,
    )

    qdrant.ensure_collection.assert_awaited_once_with(ctx.tenant_id, 1024)
    repo.add.assert_awaited_once()
    assert result.name == "docs"
    assert result.embedding_selection.dim == 1024


@pytest.mark.asyncio
async def test_create_knowledge_base_rejects_duplicate_name() -> None:
    session = MagicMock()
    ctx = _ctx()
    qdrant = MagicMock()
    qdrant.ensure_collection = AsyncMock()
    repo = MagicMock()
    existing = MagicMock(name="row")
    repo.find_by_name = AsyncMock(return_value=existing)

    with pytest.raises(ValidationError, match="already exists"):
        await create_knowledge_base(
            session,
            ctx,
            qdrant,
            repo_factory=lambda s, c: repo,
            name="docs",
            description=None,
            chunking_config=ChunkingConfig.default(),
            embedding_selection=_selection(),
        )

    qdrant.ensure_collection.assert_not_called()


@pytest.mark.asyncio
async def test_update_knowledge_base_flags_reindex_when_embedding_changes() -> None:
    session = MagicMock()
    session.flush = AsyncMock()
    ctx = _ctx()
    old_selection = _selection()
    new_selection = EmbeddingSelection(
        provider_id="ollama",
        credential_id=old_selection.credential_id,
        model_id="nomic-embed-text",
        dim=768,
    )
    existing = MagicMock()
    existing.embedding_selection = old_selection.to_dict()
    existing.chunking_config = ChunkingConfig.default().to_dict()
    existing.id = uuid4()
    existing.tenant_id = ctx.tenant_id
    existing.name = "docs"
    existing.description = None
    existing.created_at = None
    existing.updated_at = None
    repo = MagicMock()
    repo.get = AsyncMock(return_value=existing)
    qdrant = MagicMock()
    qdrant.ensure_collection = AsyncMock(return_value="kb_chunks__t__768")

    result = await update_knowledge_base(
        session,
        ctx,
        qdrant,
        repo_factory=lambda s, c: repo,
        kb_id=existing.id,
        name=None,
        description=None,
        chunking_config=None,
        embedding_selection=new_selection,
    )

    assert result.reindex_required is True
    qdrant.ensure_collection.assert_awaited_once_with(ctx.tenant_id, 768)


@pytest.mark.asyncio
async def test_update_knowledge_base_no_reindex_when_only_name_changes() -> None:
    session = MagicMock()
    session.flush = AsyncMock()
    ctx = _ctx()
    selection = _selection()
    existing = MagicMock()
    existing.embedding_selection = selection.to_dict()
    existing.chunking_config = ChunkingConfig.default().to_dict()
    existing.id = uuid4()
    existing.tenant_id = ctx.tenant_id
    existing.name = "old"
    existing.description = None
    existing.created_at = None
    existing.updated_at = None
    repo = MagicMock()
    repo.get = AsyncMock(return_value=existing)
    qdrant = MagicMock()

    result = await update_knowledge_base(
        session,
        ctx,
        qdrant,
        repo_factory=lambda s, c: repo,
        kb_id=existing.id,
        name="new",
        description=None,
        chunking_config=None,
        embedding_selection=None,
    )

    assert result.reindex_required is False
    qdrant.ensure_collection.assert_not_called()
    assert existing.name == "new"


@pytest.mark.asyncio
async def test_list_knowledge_bases_uses_pagination() -> None:
    session = MagicMock()
    ctx = _ctx()
    repo = MagicMock()
    repo.list = AsyncMock(return_value=[])

    await list_knowledge_bases(
        session, ctx, repo_factory=lambda s, c: repo, limit=5, offset=10
    )

    repo.list.assert_awaited_once_with(limit=5, offset=10)


@pytest.mark.asyncio
async def test_delete_knowledge_base_calls_repo() -> None:
    session = MagicMock()
    ctx = _ctx()
    repo = MagicMock()
    repo.delete = AsyncMock()
    kb_id = uuid4()

    await delete_knowledge_base(
        session, ctx, repo_factory=lambda s, c: repo, kb_id=kb_id
    )

    repo.delete.assert_awaited_once_with(kb_id)


@pytest.mark.asyncio
async def test_list_sources_loads_kb_then_lists() -> None:
    session = MagicMock()
    ctx = _ctx()
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.id = uuid4()
    kb_repo.get = AsyncMock(return_value=kb_row)
    src_repo = MagicMock()
    src_repo.list_by_kb = AsyncMock(return_value=[])

    result = await list_sources(
        session, ctx,
        kb_repo_factory=lambda s, c: kb_repo,
        sources_repo_factory=lambda s: src_repo,
        kb_id=kb_row.id,
    )

    kb_repo.get.assert_awaited_once_with(kb_row.id)
    src_repo.list_by_kb.assert_awaited_once_with(kb_row.id)
    assert result == []


@pytest.mark.asyncio
async def test_list_sources_raises_when_kb_missing() -> None:
    from tfm_rag.domain.errors.common import NotFoundError

    session = MagicMock()
    ctx = _ctx()
    kb_repo = MagicMock()
    kb_repo.get = AsyncMock(side_effect=NotFoundError("nope"))
    src_repo = MagicMock()
    kb_id = uuid4()

    with pytest.raises(KnowledgeBaseNotFoundError):
        await list_sources(
            session, ctx,
            kb_repo_factory=lambda s, c: kb_repo,
            sources_repo_factory=lambda s: src_repo,
            kb_id=kb_id,
        )


@pytest.mark.asyncio
async def test_detach_source_validates_kb_and_deletes() -> None:
    session = MagicMock()
    ctx = _ctx()
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.id = uuid4()
    kb_repo.get = AsyncMock(return_value=kb_row)
    src_repo = MagicMock()
    src_repo.delete = AsyncMock()
    source_id = uuid4()

    await detach_source(
        session, ctx,
        kb_repo_factory=lambda s, c: kb_repo,
        sources_repo_factory=lambda s: src_repo,
        kb_id=kb_row.id,
        source_id=source_id,
    )

    src_repo.delete.assert_awaited_once_with(kb_row.id, source_id)


@pytest.mark.asyncio
async def test_detach_source_raises_when_source_missing() -> None:
    session = MagicMock()
    ctx = _ctx()
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.id = uuid4()
    kb_repo.get = AsyncMock(return_value=kb_row)
    src_repo = MagicMock()
    src_repo.delete = AsyncMock(side_effect=SourceNotFoundError("nope"))

    with pytest.raises(SourceNotFoundError):
        await detach_source(
            session, ctx,
            kb_repo_factory=lambda s, c: kb_repo,
            sources_repo_factory=lambda s: src_repo,
            kb_id=kb_row.id,
            source_id=uuid4(),
        )


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
