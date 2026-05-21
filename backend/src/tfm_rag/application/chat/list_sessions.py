from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.infrastructure.persistence.repositories.chat_sessions_repo import (
    ChatSessionRepository,
)
from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
    ChatbotRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

ChatbotRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatbotRepository
]
SessionRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatSessionRepository
]


def _default_chatbot_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatbotRepository:
    return ChatbotRepository(session, ctx)


def _default_session_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatSessionRepository:
    return ChatSessionRepository(session, ctx)


@dataclass(frozen=True, slots=True)
class SessionSummaryView:
    id: UUID
    chatbot_id: UUID
    origin: Literal["playground", "widget"]
    created_at: datetime
    last_activity_at: datetime


async def list_sessions(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    chatbot_repo_factory: ChatbotRepoFactory = _default_chatbot_repo,
    session_repo_factory: SessionRepoFactory = _default_session_repo,
    chatbot_id: UUID,
    limit: int = 20,
    offset: int = 0,
) -> list[SessionSummaryView]:
    chatbot_repo = chatbot_repo_factory(session, ctx)
    try:
        await chatbot_repo.get(chatbot_id)
    except NotFoundError as exc:
        raise ChatbotNotFoundError(str(exc)) from exc

    session_repo = session_repo_factory(session, ctx)
    rows = await session_repo.list_by_chatbot(
        chatbot_id=chatbot_id, limit=limit, offset=offset
    )
    return [
        SessionSummaryView(
            id=r.id,
            chatbot_id=r.chatbot_id,
            origin=r.origin,  # type: ignore[arg-type]
            created_at=r.created_at,
            last_activity_at=r.last_activity_at,
        )
        for r in rows
    ]
