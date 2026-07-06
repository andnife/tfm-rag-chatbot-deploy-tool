from dataclasses import dataclass
from uuid import UUID

from tfm_rag.domain.entities.knowledge_base import KnowledgeBase
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.ports.repositories import KnowledgeBaseRepositoryPort
from tfm_rag.domain.ports.vector_store import VectorStorePort
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.model_ref import ModelRef


@dataclass(frozen=True, slots=True)
class KnowledgeBaseView:
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    chunking_config: ChunkingConfig
    embedding_selection: EmbeddingSelection
    description_llm: ModelRef | None


def _to_view(kb: KnowledgeBase) -> KnowledgeBaseView:
    return KnowledgeBaseView(
        id=kb.id,
        tenant_id=kb.tenant_id,
        name=kb.name,
        description=kb.description,
        chunking_config=kb.chunking_config,
        embedding_selection=kb.embedding_selection,
        description_llm=kb.description_llm,
    )


async def create_knowledge_base(
    *,
    kb_repo: KnowledgeBaseRepositoryPort,
    qdrant: VectorStorePort,
    tenant_id: UUID,
    name: str,
    description: str | None,
    chunking_config: ChunkingConfig,
    embedding_selection: EmbeddingSelection,
    description_llm: ModelRef | None = None,
) -> KnowledgeBaseView:
    name = name.strip()
    if not name:
        raise ValidationError("name must not be empty")
    if await kb_repo.find_by_name(name) is not None:
        raise ValidationError(f"KnowledgeBase named {name!r} already exists in tenant")

    # Provision the Qdrant collection for the chosen embedding dim before
    # persisting the KB so downstream ingestion can rely on it.
    await qdrant.ensure_collection(tenant_id, embedding_selection.dim)

    kb = await kb_repo.create_knowledge_base(
        name=name,
        description=description,
        chunking_config=chunking_config,
        embedding_selection=embedding_selection,
        description_llm=description_llm,
    )
    return _to_view(kb)
