import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import (
    IncompatibleEmbeddingsError,
    KnowledgeBaseNotFoundError,
)
from tfm_rag.domain.ports.reranker import Reranker
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk
from tfm_rag.infrastructure.embedders.dispatcher import EmbedderDispatcher
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.settings import Settings
from tfm_rag.infrastructure.vector_store.qdrant_client import (
    QdrantStore,
    collection_name_for,
)

_log = logging.getLogger(__name__)

KbRepoFactory = Callable[
    [AsyncSession, RequestContext], KnowledgeBaseRepository
]


def _default_kb_repo(
    session: AsyncSession, ctx: RequestContext
) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session, ctx)


_PAYLOAD_PROMOTED_KEYS: frozenset[str] = frozenset(
    {"tenant_id", "kb_id", "source_id", "chunk_index", "content", "source_filename"}
)


def _hit_to_chunk(point_id: str, score: float, payload: dict[str, Any]) -> RetrievedChunk:
    """Translate a raw Qdrant hit into a domain RetrievedChunk."""
    return RetrievedChunk(
        point_id=point_id,
        content=str(payload.get("content", "")),
        source_id=UUID(str(payload["source_id"])),
        source_filename=str(payload.get("source_filename", "")),
        chunk_index=int(payload.get("chunk_index", 0)),
        score=score,
        metadata={
            k: v for k, v in payload.items() if k not in _PAYLOAD_PROMOTED_KEYS
        },
    )


async def _load_and_validate_kbs(
    kb_repo: KnowledgeBaseRepository, kb_ids: list[UUID]
) -> EmbeddingSelection:
    """Load each KB, enforce they share embedding_selection. Returns the
    shared selection.
    """
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
                "Attached KBs disagree on embedding_selection. "
                f"Got {first.to_dict()} and {other.to_dict()}."
            )
    return first


async def retrieve_docs(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    qdrant: QdrantStore,
    dispatcher: EmbedderDispatcher,
    settings: Settings,
    kb_repo_factory: KbRepoFactory = _default_kb_repo,
    kb_ids: list[UUID],
    query: str,
    top_k: int,
    score_threshold: float | None,
    reranker: Reranker | None = None,
    reranker_initial_top_k: int = 30,
) -> list[RetrievedChunk]:
    """Embed `query`, vector-search Qdrant filtered by tenant_id + kb_ids,
    optionally rerank, return the top_k chunks.

    Raises:
      - KnowledgeBaseNotFoundError if any kb_id is missing in the tenant.
      - IncompatibleEmbeddingsError if the KBs disagree on embedding_selection.
      - UnsupportedProviderError if the embedder dispatcher has no entry for
        the selection's provider.
    """
    if not query.strip():
        return []
    if not kb_ids:
        return []

    kb_repo = kb_repo_factory(session, ctx)
    selection = await _load_and_validate_kbs(kb_repo, kb_ids)

    # Plan #12 only wires Ollama. base_url comes from settings (SERVER_ENV).
    # Once TENANT_CREDENTIAL providers are added, we'll decrypt the
    # credential row indicated by selection.credential_id.
    embedder = dispatcher.for_provider(selection.provider_id)
    base_url = settings.ollama_base_url  # only Ollama path today

    vectors = await embedder.embed(
        base_url=base_url,
        api_key=None,
        model_id=selection.model_id,
        texts=[query],
    )
    query_vec = vectors[0]

    collection = collection_name_for(ctx.tenant_id, selection.dim)
    search_top_k = reranker_initial_top_k if reranker is not None else top_k
    hits = await qdrant.search(
        collection=collection,
        tenant_id=ctx.tenant_id,
        kb_ids=kb_ids,
        query_vector=query_vec,
        top_k=search_top_k,
        score_threshold=score_threshold,
    )

    chunks = [_hit_to_chunk(pid, score, payload) for pid, score, payload in hits]

    if reranker is not None:
        chunks = await reranker.rerank(query=query, candidates=chunks, top_k=top_k)
    else:
        chunks = chunks[:top_k]

    return chunks
