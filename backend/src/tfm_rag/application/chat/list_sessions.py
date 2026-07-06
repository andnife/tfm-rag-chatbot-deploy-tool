from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.ports.repositories import (
    ChatbotRepositoryPort,
    ChatSessionRepositoryPort,
)


@dataclass(frozen=True, slots=True)
class SessionSummaryView:
    id: UUID
    chatbot_id: UUID
    origin: Literal["playground", "widget"]
    created_at: datetime
    last_activity_at: datetime


async def list_sessions(
    *,
    chatbot_repo: ChatbotRepositoryPort,
    session_repo: ChatSessionRepositoryPort,
    chatbot_id: UUID,
    limit: int = 20,
    offset: int = 0,
) -> list[SessionSummaryView]:
    if not await chatbot_repo.chatbot_exists(chatbot_id):
        raise ChatbotNotFoundError(f"Chatbot({chatbot_id}) not found in tenant")

    sessions = await session_repo.list_chat_sessions_by_chatbot(
        chatbot_id=chatbot_id, limit=limit, offset=offset
    )
    return [
        SessionSummaryView(
            id=s.id,
            chatbot_id=s.chatbot_id,
            origin=s.origin,
            created_at=s.created_at,
            last_activity_at=s.last_activity_at,
        )
        for s in sessions
    ]
