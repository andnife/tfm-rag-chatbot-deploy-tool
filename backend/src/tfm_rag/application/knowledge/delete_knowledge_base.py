import logging
from uuid import UUID

from tfm_rag.domain.entities.source import Source
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError
from tfm_rag.domain.ports.repositories import (
    KnowledgeBaseRepositoryPort,
    SourceRepositoryPort,
)
from tfm_rag.domain.ports.storage import Storage
from tfm_rag.domain.ports.vector_store import VectorStorePort
from tfm_rag.domain.services.collection_naming import collection_name_for

_log = logging.getLogger(__name__)


async def delete_knowledge_base(
    *,
    kb_repo: KnowledgeBaseRepositoryPort,
    sources_repo: SourceRepositoryPort,
    tenant_id: UUID,
    qdrant: VectorStorePort | None = None,
    storage: Storage | None = None,
    kb_id: UUID,
) -> None:
    """Delete a KB and, when ``qdrant``/``storage`` are provided, purge the
    indexed chunks and uploaded files of every source it contains.

    Cleanup runs ONLY after the SQL delete commits. The chatbot FK is
    RESTRICT, so a referenced KB raises ``KnowledgeBaseInUseError`` and we
    leave Qdrant/storage untouched — the KB still exists.
    """
    cleanup = qdrant is not None or storage is not None

    sources_to_clean: list[Source] = []
    selection_dim: int | None = None
    if cleanup:
        try:
            kb = await kb_repo.get_knowledge_base(kb_id)
        except NotFoundError as exc:
            raise KnowledgeBaseNotFoundError(str(exc)) from exc
        selection_dim = kb.embedding_selection.dim
        sources_to_clean = await sources_repo.list_sources_by_kb(kb_id)

    # Commits internally (raises KnowledgeBaseNotFoundError / KnowledgeBaseInUseError).
    await kb_repo.delete_knowledge_base(kb_id)

    # SQL delete is durable — now purge external stores. Best-effort per source
    # so one failure doesn't orphan the rest.
    for src in sources_to_clean:
        if qdrant is not None and selection_dim is not None:
            try:
                await qdrant.delete_by_source(
                    collection=collection_name_for(tenant_id, selection_dim),
                    tenant_id=tenant_id,
                    source_id=src.id,
                )
            except Exception:  # noqa: BLE001
                _log.warning(
                    "delete_knowledge_base: qdrant purge failed for source %s",
                    src.id,
                )
        if storage is not None and src.type == "document":
            uri = (src.payload or {}).get("storage_uri")
            if uri:
                try:
                    await storage.delete(uri)
                except Exception:  # noqa: BLE001
                    _log.warning(
                        "delete_knowledge_base: storage delete failed for %s", uri
                    )
