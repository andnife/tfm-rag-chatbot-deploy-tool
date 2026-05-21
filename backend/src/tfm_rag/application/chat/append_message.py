from collections.abc import Callable
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.chat import SessionNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.infrastructure.persistence.repositories.chat_sessions_repo import (
    ChatMessageRepository,
    ChatSessionRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

SessionRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatSessionRepository
]
MessageRepoFactory = Callable[[AsyncSession], ChatMessageRepository]


def _default_session_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatSessionRepository:
    return ChatSessionRepository(session, ctx)


def _default_message_repo(session: AsyncSession) -> ChatMessageRepository:
    return ChatMessageRepository(session)


async def append_message(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    session_repo_factory: SessionRepoFactory = _default_session_repo,
    message_repo_factory: MessageRepoFactory = _default_message_repo,
    session_id: UUID,
    role: Literal["user", "assistant", "system"],
    content: str,
    citations: list[dict[str, Any]] | None,
    metadata: dict[str, Any] | None,
) -> UUID:
    """Internal helper. Plan #15's agent loop calls this per turn."""
    session_repo = session_repo_factory(session, ctx)
    try:
        await session_repo.get(session_id)
    except NotFoundError as exc:
        raise SessionNotFoundError(str(exc)) from exc

    message_repo = message_repo_factory(session)
    row = await message_repo.append(
        session_id=session_id,
        role=role,
        content=content,
        citations=citations,
        metadata=metadata,
    )
    return row.id
