from collections.abc import Callable
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError, ValidationError
from tfm_rag.infrastructure.persistence.models.chat_sessions import (
    ChatSessionRow,
)
from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
    ChatbotRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

ChatbotRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatbotRepository
]


def _default_chatbot_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatbotRepository:
    return ChatbotRepository(session, ctx)


async def create_session(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    chatbot_repo_factory: ChatbotRepoFactory = _default_chatbot_repo,
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

    chatbot_repo = chatbot_repo_factory(session, ctx)
    try:
        await chatbot_repo.get(chatbot_id)
    except NotFoundError as exc:
        raise ChatbotNotFoundError(str(exc)) from exc

    session_id = uuid4()
    row = ChatSessionRow(
        id=session_id,
        chatbot_id=chatbot_id,
        tenant_id=ctx.tenant_id,
        origin=origin,
        public_session_cookie=public_session_cookie,
    )
    session.add(row)
    await session.flush()
    return session_id
