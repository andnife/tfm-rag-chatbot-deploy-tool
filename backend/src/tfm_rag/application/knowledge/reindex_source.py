from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.knowledge import (
    KnowledgeBaseNotFoundError,
    SourceNotFoundError,
)
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repositories.sources_repo import (
    SourceRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.vector_store.qdrant_client import (
    QdrantStore,
    collection_name_for,
)

KbRepoFactory = Callable[
    [AsyncSession, RequestContext], KnowledgeBaseRepository
]
SrcRepoFactory = Callable[[AsyncSession], SourceRepository]


def _default_kb_repo(
    session: AsyncSession, ctx: RequestContext
) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session, ctx)


def _default_src_repo(session: AsyncSession) -> SourceRepository:
    return SourceRepository(session)


async def purge_source_chunks(
    session: AsyncSession,
    ctx: RequestContext,
    qdrant: QdrantStore,
    *,
    kb_repo_factory: KbRepoFactory = _default_kb_repo,
    sources_repo_factory: SrcRepoFactory = _default_src_repo,
    kb_id: UUID,
    source_id: UUID,
) -> None:
    """Idempotent: delete existing Qdrant chunks for `source_id`.

    Used by ReindexSource before re-running the pipeline. Lives here (not in
    `ingest_source.py`) because reindexing is the only caller in plan #8.
    The KB's embedding `dim` selects the collection.
    """
    kb_repo = kb_repo_factory(session, ctx)
    try:
        kb_row = await kb_repo.get(kb_id)
    except Exception as exc:
        raise KnowledgeBaseNotFoundError(str(exc)) from exc
    src_repo = sources_repo_factory(session)
    try:
        await src_repo.get(kb_id, source_id)
    except Exception as exc:
        raise SourceNotFoundError(str(exc)) from exc

    selection = EmbeddingSelection.from_dict(kb_row.embedding_selection)
    collection = collection_name_for(ctx.tenant_id, selection.dim)
    await qdrant.delete_by_source(
        collection=collection,
        tenant_id=ctx.tenant_id,
        source_id=source_id,
    )
