from typing import Literal
from uuid import UUID

from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.ports.repositories import (
    ChatbotRepositoryPort,
    ChatSessionRepositoryPort,
)


async def create_session(
    *,
    chatbot_repo: ChatbotRepositoryPort,
    session_repo: ChatSessionRepositoryPort,
    chatbot_id: UUID,
    origin: Literal["playground", "widget"],
    public_session_cookie: str | None,
) -> UUID:
    """Internal helper. Plan #15's agent loop calls this to start a session.

    Validates that the chatbot exists in the tenant before creating the
    session row. `widget` origin requires `public_session_cookie`;
    `playground` requires None.
    """
    if origin not in ("playground", "widget"):
        raise ValidationError(f"Unknown session origin: {origin!r}")
    if origin == "widget" and not public_session_cookie:
        raise ValidationError(
            "origin=widget requires a public_session_cookie value"
        )
    if origin == "playground" and public_session_cookie is not None:
        raise ValidationError(
            "origin=playground must not carry a public_session_cookie"
        )

    if not await chatbot_repo.chatbot_exists(chatbot_id):
        raise ChatbotNotFoundError(f"Chatbot({chatbot_id}) not found in tenant")

    return await session_repo.create_chat_session(
        chatbot_id=chatbot_id,
        origin=origin,
        public_session_cookie=public_session_cookie,
    )
