import secrets
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from tfm_rag.domain.entities.chatbot import Chatbot
from tfm_rag.domain.errors.chatbot import ChatbotAlreadyExistsError
from tfm_rag.domain.errors.common import NotFoundError, ValidationError
from tfm_rag.domain.errors.knowledge import (
    IncompatibleEmbeddingsError,
    KnowledgeBaseNotFoundError,
)
from tfm_rag.domain.ports.repositories import (
    ChatbotRepositoryPort,
    KnowledgeBaseRepositoryPort,
)
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.domain.value_objects.role_llm_selections import RoleLLMSelections
from tfm_rag.domain.value_objects.widget_config import WidgetConfig


def _generate_public_key() -> str:
    return "wgt_" + secrets.token_urlsafe(32)


@dataclass(frozen=True, slots=True)
class ChatbotView:
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    system_prompt: str
    llm_selection: LLMSelection
    role_llm_selections: RoleLLMSelections
    pipeline_config: PipelineConfig
    widget_config: dict[str, Any]
    public_key: str
    kb_ids: list[UUID]


def _to_view(chatbot: Chatbot) -> ChatbotView:
    return ChatbotView(
        id=chatbot.id,
        tenant_id=chatbot.tenant_id,
        name=chatbot.name,
        description=chatbot.description,
        system_prompt=chatbot.system_prompt,
        llm_selection=chatbot.llm_selection,
        role_llm_selections=chatbot.role_llm_selections,
        pipeline_config=chatbot.pipeline_config,
        widget_config=chatbot.widget_config.to_dict(),
        public_key=chatbot.public_key,
        kb_ids=chatbot.kb_ids,
    )


async def _validate_kb_compatibility(
    kb_repo: KnowledgeBaseRepositoryPort, kb_ids: list[UUID]
) -> None:
    """Load each KB (tenant-scoped via the port), enforce that they all share
    the same `embedding_selection`.
    """
    if not kb_ids:
        return
    selections: list[EmbeddingSelection] = []
    for kb_id in kb_ids:
        try:
            kb = await kb_repo.get_knowledge_base(kb_id)
        except NotFoundError as exc:
            raise KnowledgeBaseNotFoundError(str(exc)) from exc
        selections.append(kb.embedding_selection)
    first = selections[0]
    for other in selections[1:]:
        if other != first:
            raise IncompatibleEmbeddingsError(
                f"Attached KBs disagree on embedding_selection. "
                f"Got {first.to_dict()} and {other.to_dict()}."
            )


async def create_chatbot(
    *,
    chatbot_repo: ChatbotRepositoryPort,
    kb_repo: KnowledgeBaseRepositoryPort,
    name: str,
    description: str | None,
    system_prompt: str,
    llm_selection: LLMSelection,
    role_llm_selections: RoleLLMSelections | None = None,
    kb_ids: list[UUID],
    pipeline_config: PipelineConfig,
    widget_config: WidgetConfig,
) -> ChatbotView:
    name = name.strip()
    if not name:
        raise ValidationError("name must not be empty")
    if not system_prompt.strip():
        raise ValidationError("system_prompt must not be empty")

    if await chatbot_repo.find_chatbot_by_name(name) is not None:
        raise ChatbotAlreadyExistsError(
            f"Chatbot named {name!r} already exists in tenant"
        )

    await _validate_kb_compatibility(kb_repo, kb_ids)

    chatbot = await chatbot_repo.create_chatbot(
        name=name,
        description=description,
        system_prompt=system_prompt,
        llm_selection=llm_selection,
        role_llm_selections=role_llm_selections or RoleLLMSelections.default(),
        pipeline_config=pipeline_config,
        widget_config=widget_config,
        public_key=_generate_public_key(),
        kb_ids=kb_ids,
    )
    return _to_view(chatbot)
