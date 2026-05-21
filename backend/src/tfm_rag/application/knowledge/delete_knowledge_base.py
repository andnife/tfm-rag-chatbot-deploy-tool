from collections.abc import Callable
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import (
    KnowledgeBaseInUseError,
    KnowledgeBaseNotFoundError,
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


async def delete_knowledge_base(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    repo_factory: KbRepoFactory = _default_repo,
    kb_id: UUID,
) -> None:
    repo = repo_factory(session, ctx)
    try:
        await repo.delete(kb_id)
    except NotFoundError as exc:
        raise KnowledgeBaseNotFoundError(str(exc)) from exc
    except IntegrityError as exc:
        # Plan #10 wires the chatbot_knowledge_base RESTRICT FK; this maps
        # the DB-layer violation to the domain error so callers can render
        # the right 409 response without depending on SQLAlchemy types.
        raise KnowledgeBaseInUseError(
            f"KnowledgeBase({kb_id}) is referenced by a chatbot"
        ) from exc
