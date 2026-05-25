from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.chatbot_config.create_chatbot import (
    ChatbotView,
    _to_view,
    _validate_kb_compatibility,
)
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError, ValidationError
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.domain.value_objects.widget_config import WidgetConfig
from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
    ChatbotRepository,
)
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

ChatbotRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatbotRepository
]
KbRepoFactory = Callable[
    [AsyncSession, RequestContext], KnowledgeBaseRepository
]


def _default_chatbot_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatbotRepository:
    return ChatbotRepository(session, ctx)


def _default_kb_repo(
    session: AsyncSession, ctx: RequestContext
) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session, ctx)


async def update_chatbot(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    chatbot_repo_factory: ChatbotRepoFactory = _default_chatbot_repo,
    kb_repo_factory: KbRepoFactory = _default_kb_repo,
    chatbot_id: UUID,
    name: str | None,
    description: str | None,
    system_prompt: str | None,
    llm_selection: LLMSelection | None,
    kb_ids: list[UUID] | None,
    pipeline_config: PipelineConfig | None,
    widget_config: WidgetConfig | None,
) -> ChatbotView:
    chatbot_repo = chatbot_repo_factory(session, ctx)
    try:
        row = await chatbot_repo.get(chatbot_id)
    except NotFoundError as exc:
        raise ChatbotNotFoundError(str(exc)) from exc

    if name is not None:
        name = name.strip()
        if not name:
            raise ValidationError("name must not be empty")
        row.name = name
    if description is not None:
        row.description = description or None
    if system_prompt is not None:
        if not system_prompt.strip():
            raise ValidationError("system_prompt must not be empty")
        row.system_prompt = system_prompt
    if llm_selection is not None:
        row.llm_selection = llm_selection.to_dict()
    if pipeline_config is not None:
        row.pipeline_config = pipeline_config.to_dict()
        row.router_llm_selection = (
            pipeline_config.router_llm_selection.to_dict()
            if pipeline_config.router_llm_selection
            else None
        )
    if widget_config is not None:
        row.widget_config = widget_config.to_dict()

    current_kb_ids: list[UUID]
    if kb_ids is not None:
        # Validate the new set and replace the N:M rows.
        kb_repo = kb_repo_factory(session, ctx)
        await _validate_kb_compatibility(kb_repo, kb_ids)
        await chatbot_repo.replace_kb_links(chatbot_id, kb_ids)
        current_kb_ids = kb_ids
    else:
        current_kb_ids = await chatbot_repo.list_kb_ids(chatbot_id)

    await session.flush()
    return _to_view(row, current_kb_ids)
