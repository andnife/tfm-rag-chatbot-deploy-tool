from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.chatbot_config.create_chatbot import (
    ChatbotView,
    _to_view,
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


async def list_chatbots(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    chatbot_repo_factory: ChatbotRepoFactory = _default_chatbot_repo,
    limit: int = 20,
    offset: int = 0,
) -> list[ChatbotView]:
    repo = chatbot_repo_factory(session, ctx)
    rows = await repo.list(limit=limit, offset=offset)
    if not rows:
        return []
    # Batch-fetch KB IDs to avoid N+1 queries.
    kb_ids_map = await repo.list_kb_ids_batch([r.id for r in rows])
    return [_to_view(row, kb_ids_map.get(row.id, [])) for row in rows]
