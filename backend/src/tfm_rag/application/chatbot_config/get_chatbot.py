from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.chatbot_config.create_chatbot import (
    ChatbotView,
    _to_view,
)
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
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


async def get_chatbot(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    chatbot_repo_factory: ChatbotRepoFactory = _default_chatbot_repo,
    chatbot_id: UUID,
) -> ChatbotView:
    repo = chatbot_repo_factory(session, ctx)
    try:
        row = await repo.get(chatbot_id)
    except NotFoundError as exc:
        raise ChatbotNotFoundError(str(exc)) from exc
    kb_ids = await repo.list_kb_ids(chatbot_id)
    return _to_view(row, kb_ids)
