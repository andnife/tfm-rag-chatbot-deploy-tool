from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.infrastructure.persistence.repositories.chat_sessions_repo import (
    ChatSessionRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

SessionRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatSessionRepository
]


def _default_session_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatSessionRepository:
    return ChatSessionRepository(session, ctx)


async def touch_session(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    session_repo_factory: SessionRepoFactory = _default_session_repo,
    session_id: UUID,
) -> None:
    """Internal helper. Bumps `last_activity_at`. No-op if the session
    doesn't belong to the tenant (defense in depth — the agent loop should
    never call touch on a foreign session, but if it did we silently
    drop the update at the SQL layer via the tenant_id filter).
    """
    session_repo = session_repo_factory(session, ctx)
    await session_repo.touch(session_id)
