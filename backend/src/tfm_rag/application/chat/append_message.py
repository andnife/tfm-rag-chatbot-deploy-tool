from typing import Any, Literal
from uuid import UUID

from tfm_rag.domain.errors.chat import SessionNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.ports.repositories import (
    ChatMessageRepositoryPort,
    ChatSessionRepositoryPort,
)


async def append_message(
    *,
    session_repo: ChatSessionRepositoryPort,
    message_repo: ChatMessageRepositoryPort,
    session_id: UUID,
    role: Literal["user", "assistant", "system"],
    content: str,
    citations: list[dict[str, Any]] | None,
    metadata: dict[str, Any] | None,
) -> UUID:
    """Internal helper. Plan #15's agent loop calls this per turn."""
    try:
        await session_repo.get_chat_session(session_id)
    except NotFoundError as exc:
        raise SessionNotFoundError(str(exc)) from exc

    message = await message_repo.append_message(
        session_id=session_id,
        role=role,
        content=content,
        citations=citations,
        metadata=metadata,
    )
    return message.id
