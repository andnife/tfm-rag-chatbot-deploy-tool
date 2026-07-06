from uuid import UUID

from tfm_rag.application.chatbot_config.create_chatbot import (
    ChatbotView,
    _to_view,
    _validate_kb_compatibility,
)
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError, ValidationError
from tfm_rag.domain.ports.repositories import (
    ChatbotRepositoryPort,
    KnowledgeBaseRepositoryPort,
)
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.domain.value_objects.role_llm_selections import RoleLLMSelections
from tfm_rag.domain.value_objects.widget_config import WidgetConfig


async def update_chatbot(
    *,
    chatbot_repo: ChatbotRepositoryPort,
    kb_repo: KnowledgeBaseRepositoryPort,
    chatbot_id: UUID,
    name: str | None,
    description: str | None,
    system_prompt: str | None,
    llm_selection: LLMSelection | None,
    role_llm_selections: RoleLLMSelections | None = None,
    kb_ids: list[UUID] | None,
    pipeline_config: PipelineConfig | None,
    widget_config: WidgetConfig | None,
) -> ChatbotView:
    try:
        current = await chatbot_repo.get_chatbot(chatbot_id)
    except NotFoundError as exc:
        raise ChatbotNotFoundError(str(exc)) from exc

    new_name = current.name
    if name is not None:
        name = name.strip()
        if not name:
            raise ValidationError("name must not be empty")
        new_name = name

    new_description = (
        current.description if description is None else (description or None)
    )

    new_system_prompt = current.system_prompt
    if system_prompt is not None:
        if not system_prompt.strip():
            raise ValidationError("system_prompt must not be empty")
        new_system_prompt = system_prompt

    new_llm_selection = (
        current.llm_selection if llm_selection is None else llm_selection
    )
    new_role_llm_selections = (
        current.role_llm_selections
        if role_llm_selections is None
        else role_llm_selections
    )
    new_pipeline_config = (
        current.pipeline_config if pipeline_config is None else pipeline_config
    )
    new_widget_config = (
        current.widget_config if widget_config is None else widget_config
    )

    if kb_ids is not None:
        await _validate_kb_compatibility(kb_repo, kb_ids)

    updated = await chatbot_repo.update_chatbot(
        chatbot_id,
        name=new_name,
        description=new_description,
        system_prompt=new_system_prompt,
        llm_selection=new_llm_selection,
        role_llm_selections=new_role_llm_selections,
        pipeline_config=new_pipeline_config,
        widget_config=new_widget_config,
        kb_ids=kb_ids,
    )
    return _to_view(updated)
