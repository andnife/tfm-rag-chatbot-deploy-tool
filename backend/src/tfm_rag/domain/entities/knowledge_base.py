from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.model_ref import ModelRef


@dataclass(frozen=True, slots=True)
class KnowledgeBase:
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    chunking_config: ChunkingConfig
    embedding_selection: EmbeddingSelection
    created_at: datetime
    updated_at: datetime
    # Optional first-class LLM used to auto-generate per-document descriptions
    # at ingestion time (C1). None => description generation is skipped.
    description_llm: ModelRef | None = None
