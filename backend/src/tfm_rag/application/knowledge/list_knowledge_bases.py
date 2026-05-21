from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.knowledge.create_knowledge_base import (
    KnowledgeBaseView,
    _to_view,
)
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

KbRepoFactory = Callable[
    [AsyncSession, RequestContext], KnowledgeBaseRepository
]


def _default_repo(
    session: AsyncSession, ctx: RequestContext
) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session, ctx)


async def list_knowledge_bases(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    repo_factory: KbRepoFactory = _default_repo,
    limit: int = 20,
    offset: int = 0,
) -> list[KnowledgeBaseView]:
    repo = repo_factory(session, ctx)
    rows = await repo.list(limit=limit, offset=offset)
    return [_to_view(r) for r in rows]
