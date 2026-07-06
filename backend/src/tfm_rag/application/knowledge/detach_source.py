from uuid import UUID

from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError
from tfm_rag.domain.ports.repositories import (
    KnowledgeBaseRepositoryPort,
    SourceRepositoryPort,
)
from tfm_rag.domain.ports.storage import Storage
from tfm_rag.domain.ports.vector_store import VectorStorePort
from tfm_rag.domain.services.collection_naming import collection_name_for


async def detach_source(
    *,
    kb_repo: KnowledgeBaseRepositoryPort,
    sources_repo: SourceRepositoryPort,
    tenant_id: UUID,
    qdrant: VectorStorePort | None = None,
    storage: Storage | None = None,
    kb_id: UUID,
    source_id: UUID,
) -> None:
    """Remove a Source row from a KB, plus its Qdrant chunks and storage file.

    When `qdrant` is provided, deletes any indexed chunks for this source in
    Qdrant before removing the SQL row (`delete_by_source` is a filter-based
    no-op when nothing matches). When `storage` is provided, also deletes the
    uploaded file of a document source (otherwise it leaks on disk).
    """
    try:
        kb = await kb_repo.get_knowledge_base(kb_id)
    except NotFoundError as exc:
        raise KnowledgeBaseNotFoundError(str(exc)) from exc

    # Resolve the file to delete BEFORE removing the row (we need its payload).
    storage_uri: str | None = None
    if storage is not None:
        src = await sources_repo.get_source(kb_id, source_id)
        if src.type == "document":
            storage_uri = (src.payload or {}).get("storage_uri")

    if qdrant is not None:
        collection = collection_name_for(tenant_id, kb.embedding_selection.dim)
        await qdrant.delete_by_source(
            collection=collection,
            tenant_id=tenant_id,
            source_id=source_id,
        )

    # Commits internally so external cleanup runs against a durable delete.
    await sources_repo.delete_source(kb_id, source_id)

    if storage is not None and storage_uri:
        await storage.delete(storage_uri)
