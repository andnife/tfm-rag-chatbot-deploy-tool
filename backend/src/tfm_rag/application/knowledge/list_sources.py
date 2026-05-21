from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.knowledge.get_knowledge_base import (
    SourceView,
    _src_view,
)
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


async def list_sources(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    kb_repo_factory: KbRepoFactory = _default_kb_repo,
    sources_repo_factory: SrcRepoFactory = _default_src_repo,
    kb_id: UUID,
) -> list[SourceView]:
    kb_repo = kb_repo_factory(session, ctx)
    try:
        await kb_repo.get(kb_id)
    except NotFoundError as exc:
        raise KnowledgeBaseNotFoundError(str(exc)) from exc
    src_repo = sources_repo_factory(session)
    rows = await src_repo.list_by_kb(kb_id)
    return [_src_view(r) for r in rows]
