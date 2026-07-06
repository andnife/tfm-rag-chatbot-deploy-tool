from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from tfm_rag.domain.errors.chat import SessionNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.ports.repositories import (
    ChatMessageRepositoryPort,
    ChatSessionRepositoryPort,
)


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
    *,
    session_repo: ChatSessionRepositoryPort,
    message_repo: ChatMessageRepositoryPort,
    session_id: UUID,
) -> SessionDetailView:
    try:
        s = await session_repo.get_chat_session(session_id)
    except NotFoundError as exc:
        raise SessionNotFoundError(str(exc)) from exc

    messages = await message_repo.list_messages_by_session(session_id)

    return SessionDetailView(
        session=SessionView(
            id=s.id,
            chatbot_id=s.chatbot_id,
            origin=s.origin,
            created_at=s.created_at,
            last_activity_at=s.last_activity_at,
        ),
        messages=[
            MessageView(
                id=m.id,
                session_id=m.session_id,
                role=m.role,
                content=m.content,
                citations=m.citations,
                metadata=m.metadata,
                created_at=m.created_at,  # type: ignore[arg-type]
            )
            for m in messages
        ],
    )
