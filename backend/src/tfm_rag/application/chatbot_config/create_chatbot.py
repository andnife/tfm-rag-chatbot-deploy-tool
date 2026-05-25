import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.chatbot import ChatbotAlreadyExistsError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import (
    IncompatibleEmbeddingsError,
    KnowledgeBaseNotFoundError,
)
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.domain.value_objects.widget_config import WidgetConfig
from tfm_rag.infrastructure.persistence.models.chatbots import ChatbotRow
from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
    ChatbotRepository,
)
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext


def _generate_public_key() -> str:
    return "wgt_" + secrets.token_urlsafe(32)


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


@dataclass(frozen=True, slots=True)
class ChatbotView:
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    system_prompt: str
    llm_selection: LLMSelection
    pipeline_config: PipelineConfig
    widget_config: dict[str, Any]
    public_key: str
    kb_ids: list[UUID]


def _to_view(row: ChatbotRow, kb_ids: list[UUID]) -> ChatbotView:
    return ChatbotView(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        description=row.description,
        system_prompt=row.system_prompt,
        llm_selection=LLMSelection.from_dict(row.llm_selection),
        pipeline_config=PipelineConfig.from_dict(row.pipeline_config),
        widget_config=row.widget_config,
        public_key=row.public_key,
        kb_ids=kb_ids,
    )


async def _validate_kb_compatibility(
    kb_repo: KnowledgeBaseRepository, kb_ids: list[UUID]
) -> None:
    """Load each KB (tenant-scoped via repo), enforce that they all share
    the same `embedding_selection` dict.
    """
    if not kb_ids:
        return
    selections: list[EmbeddingSelection] = []
    for kb_id in kb_ids:
        try:
            kb_row = await kb_repo.get(kb_id)
        except NotFoundError as exc:
            raise KnowledgeBaseNotFoundError(str(exc)) from exc
        selections.append(EmbeddingSelection.from_dict(kb_row.embedding_selection))
    first = selections[0]
    for other in selections[1:]:
        if other != first:
            raise IncompatibleEmbeddingsError(
                f"Attached KBs disagree on embedding_selection. "
                f"Got {first.to_dict()} and {other.to_dict()}."
            )


async def create_chatbot(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    chatbot_repo_factory: ChatbotRepoFactory = _default_chatbot_repo,
    kb_repo_factory: KbRepoFactory = _default_kb_repo,
    name: str,
    description: str | None,
    system_prompt: str,
    llm_selection: LLMSelection,
    kb_ids: list[UUID],
    pipeline_config: PipelineConfig,
    widget_config: WidgetConfig,
) -> ChatbotView:
    name = name.strip()
    if not name:
        from tfm_rag.domain.errors.common import ValidationError
        raise ValidationError("name must not be empty")
    if not system_prompt.strip():
        from tfm_rag.domain.errors.common import ValidationError
        raise ValidationError("system_prompt must not be empty")

    chatbot_repo = chatbot_repo_factory(session, ctx)
    if await chatbot_repo.find_by_name(name) is not None:
        raise ChatbotAlreadyExistsError(
            f"Chatbot named {name!r} already exists in tenant"
        )

    kb_repo = kb_repo_factory(session, ctx)
    await _validate_kb_compatibility(kb_repo, kb_ids)

    public_key = _generate_public_key()
    chatbot_id = uuid4()
    row = ChatbotRow(
        id=chatbot_id,
        tenant_id=ctx.tenant_id,
        name=name,
        description=description,
        system_prompt=system_prompt,
        llm_selection=llm_selection.to_dict(),
        router_llm_selection=(
            pipeline_config.router_llm_selection.to_dict()
            if pipeline_config.router_llm_selection
            else None
        ),
        pipeline_config=pipeline_config.to_dict(),
        widget_config=widget_config.to_dict(),
        public_key=public_key,
    )
    await chatbot_repo.add(row)
    await chatbot_repo.replace_kb_links(chatbot_id, kb_ids)
    return _to_view(row, kb_ids)
