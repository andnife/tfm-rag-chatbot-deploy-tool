from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError
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


async def delete_chatbot(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    chatbot_repo_factory: ChatbotRepoFactory = _default_chatbot_repo,
    chatbot_id: UUID,
) -> None:
    repo = chatbot_repo_factory(session, ctx)
    try:
        await repo.attempt_delete_with_cascade(chatbot_id)
    except KnowledgeBaseNotFoundError as exc:
        # The repo uses that error as a sentinel for "row not found".
        # Translate to the chatbot-scoped error so callers get the right
        # 404 message.
        raise ChatbotNotFoundError(
            f"Chatbot({chatbot_id}) not found in tenant"
        ) from exc
