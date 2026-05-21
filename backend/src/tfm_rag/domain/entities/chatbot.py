from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig


@dataclass(frozen=True, slots=True)
class Chatbot:
    """Chatbot aggregate root.

    `widget_config` stays as `dict[str, Any]` in plan #10 — a structured VO
    arrives in plan #11 CAP-CHATBOT-WIDGET-CONFIG.

    `kb_ids` is the materialised N:M projection (read from
    chatbot_knowledge_base); the entity does NOT manage the link rows
    directly — that's the use case's job.
    """

    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    system_prompt: str
    llm_selection: LLMSelection
    pipeline_config: PipelineConfig
    widget_config: dict[str, Any]
    kb_ids: list[UUID]
    created_at: datetime
    updated_at: datetime
