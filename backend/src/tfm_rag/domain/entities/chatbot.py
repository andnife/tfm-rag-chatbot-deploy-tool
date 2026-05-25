from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.domain.value_objects.widget_config import WidgetConfig


@dataclass(frozen=True, slots=True)
class Chatbot:
    """Chatbot aggregate root.

    `widget_config` is a typed WidgetConfig VO (plan #11 CAP-CHATBOT-WIDGET-CONFIG).
    `public_key` is the stable public identifier for the widget embed.

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
    widget_config: WidgetConfig
    public_key: str
    kb_ids: list[UUID]
    created_at: datetime
    updated_at: datetime
