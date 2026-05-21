from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repositories.sources_repo import (
    SourceRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

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


async def detach_source(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    kb_repo_factory: KbRepoFactory = _default_kb_repo,
    sources_repo_factory: SrcRepoFactory = _default_src_repo,
    kb_id: UUID,
    source_id: UUID,
) -> None:
    """Remove a Source row from a KB.

    Plan #7 only deletes the row. Cleanup of Qdrant chunks and storage
    artefacts for `document` sources lives in plan #8 (full ingestion
    lifecycle). The split is intentional: detach is part of the polymorphic
    surface, but per-subtype cleanup belongs with the per-subtype use cases.
    """
    kb_repo = kb_repo_factory(session, ctx)
    try:
        await kb_repo.get(kb_id)
    except NotFoundError as exc:
        raise KnowledgeBaseNotFoundError(str(exc)) from exc
    src_repo = sources_repo_factory(session)
    await src_repo.delete(kb_id, source_id)
