from uuid import UUID

from tfm_rag.domain.errors.knowledge import (
    KnowledgeBaseNotFoundError,
    SourceNotFoundError,
)
from tfm_rag.domain.ports.repositories import (
    KnowledgeBaseRepositoryPort,
    SourceRepositoryPort,
)
from tfm_rag.domain.ports.vector_store import VectorStorePort
from tfm_rag.domain.services.collection_naming import collection_name_for


async def purge_source_chunks(
    *,
    kb_repo: KnowledgeBaseRepositoryPort,
    sources_repo: SourceRepositoryPort,
    qdrant: VectorStorePort,
    tenant_id: UUID,
    kb_id: UUID,
    source_id: UUID,
) -> None:
    """Idempotent: delete existing Qdrant chunks for `source_id`.

    Used by ReindexSource before re-running the pipeline. The KB's embedding
    `dim` selects the collection.
    """
    try:
        kb = await kb_repo.get_knowledge_base(kb_id)
    except Exception as exc:  # noqa: BLE001
        raise KnowledgeBaseNotFoundError(str(exc)) from exc
    try:
        await sources_repo.get_source(kb_id, source_id)
    except Exception as exc:  # noqa: BLE001
        raise SourceNotFoundError(str(exc)) from exc

    collection = collection_name_for(tenant_id, kb.embedding_selection.dim)
    await qdrant.delete_by_source(
        collection=collection,
        tenant_id=tenant_id,
        source_id=source_id,
    )
