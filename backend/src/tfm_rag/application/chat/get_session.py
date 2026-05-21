from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
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


@dataclass(frozen=True, slots=True)
class SessionView:
    id: UUID
    chatbot_id: UUID
    origin: Literal["playground", "widget"]
    created_at: datetime
    last_activity_at: datetime


@dataclass(frozen=True, slots=True)
class MessageView:
    id: UUID
    session_id: UUID
    role: Literal["user", "assistant", "system"]
    content: str
    citations: list[dict[str, Any]]
    metadata: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SessionDetailView:
    session: SessionView
    messages: list[MessageView]


async def get_session(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    session_repo_factory: SessionRepoFactory = _default_session_repo,
    message_repo_factory: MessageRepoFactory = _default_message_repo,
    session_id: UUID,
) -> SessionDetailView:
    session_repo = session_repo_factory(session, ctx)
    try:
        s_row = await session_repo.get(session_id)
    except NotFoundError as exc:
        raise SessionNotFoundError(str(exc)) from exc

    message_repo = message_repo_factory(session)
    m_rows = await message_repo.list_by_session(session_id)

    return SessionDetailView(
        session=SessionView(
            id=s_row.id,
            chatbot_id=s_row.chatbot_id,
            origin=s_row.origin,  # type: ignore[arg-type]
            created_at=s_row.created_at,
            last_activity_at=s_row.last_activity_at,
        ),
        messages=[
            MessageView(
                id=m.id,
                session_id=m.session_id,
                role=m.role,  # type: ignore[arg-type]
                content=m.content,
                citations=m.citations,
                metadata=m.metadata_,
                created_at=m.created_at,
            )
            for m in m_rows
        ],
    )
