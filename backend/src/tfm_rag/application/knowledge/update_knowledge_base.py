from dataclasses import dataclass
from typing import Any
from uuid import UUID

from tfm_rag.application.knowledge.create_knowledge_base import (
    KnowledgeBaseView,
    _to_view,
)
from tfm_rag.domain.errors.common import NotFoundError, ValidationError
from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError
from tfm_rag.domain.ports.repositories import KnowledgeBaseRepositoryPort
from tfm_rag.domain.ports.vector_store import VectorStorePort
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.model_ref import ModelRef


class _Unset:
    """Sentinel distinguishing "field not provided" from an explicit None
    (which means "clear this optional field")."""


_UNSET: Any = _Unset()


@dataclass(frozen=True, slots=True)
class UpdateKnowledgeBaseResult:
    kb: KnowledgeBaseView
    reindex_required: bool


async def update_knowledge_base(
    *,
    kb_repo: KnowledgeBaseRepositoryPort,
    qdrant: VectorStorePort,
    tenant_id: UUID,
    kb_id: UUID,
    name: str | None,
    description: str | None,
    chunking_config: ChunkingConfig | None,
    embedding_selection: EmbeddingSelection | None,
    description_llm: ModelRef | None | _Unset = _UNSET,
) -> UpdateKnowledgeBaseResult:
    try:
        kb = await kb_repo.get_knowledge_base(kb_id)
    except NotFoundError as exc:
        raise KnowledgeBaseNotFoundError(str(exc)) from exc

    reindex = False

    new_name = kb.name
    if name is not None:
        stripped = name.strip()
        if not stripped:
            raise ValidationError("name must not be empty")
        new_name = stripped

    new_description = kb.description
    if description is not None:
        new_description = description or None

    new_chunking = kb.chunking_config
    if chunking_config is not None and chunking_config != kb.chunking_config:
        new_chunking = chunking_config
        reindex = True

    new_selection = kb.embedding_selection
    if (
        embedding_selection is not None
        and embedding_selection != kb.embedding_selection
    ):
        new_selection = embedding_selection
        if embedding_selection.dim != kb.embedding_selection.dim:
            # Provision the new (tenant, dim) collection so reindex can target it.
            await qdrant.ensure_collection(tenant_id, embedding_selection.dim)
        reindex = True

    new_description_llm = (
        kb.description_llm if isinstance(description_llm, _Unset) else description_llm
    )

    updated = await kb_repo.update_knowledge_base(
        kb_id,
        name=new_name,
        description=new_description,
        chunking_config=new_chunking,
        embedding_selection=new_selection,
        description_llm=new_description_llm,
    )
    return UpdateKnowledgeBaseResult(kb=_to_view(updated), reindex_required=reindex)
