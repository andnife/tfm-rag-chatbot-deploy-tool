import logging
from typing import Any
from uuid import UUID

from tfm_rag.application.integrations.endpoint_resolver import resolve_inference_target
from tfm_rag.domain.errors.chat import RetrievalError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import (
    IncompatibleEmbeddingsError,
    KnowledgeBaseNotFoundError,
)
from tfm_rag.domain.ports.embedder import EmbedderDispatcherPort
from tfm_rag.domain.ports.repositories import (
    KnowledgeBaseRepositoryPort,
    ProviderCredentialRepositoryPort,
)
from tfm_rag.domain.ports.reranker import Reranker
from tfm_rag.domain.ports.secret_encryptor import SecretEncryptor
from tfm_rag.domain.ports.vector_store import VectorStorePort

# Task-9 exception: pure (tenant_id, dim) -> collection-name helper. It lives in
# the Qdrant adapter today; every application module that talks to the vector
# store imports it the same way. Task 9 relocates it out of infrastructure.
from tfm_rag.domain.services.collection_naming import collection_name_for
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk

_log = logging.getLogger(__name__)


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
    kb_repo: KnowledgeBaseRepositoryPort, kb_ids: list[UUID]
) -> EmbeddingSelection:
    """Load each KB, enforce they share embedding_selection. Returns the
    shared selection.
    """
    selections: list[EmbeddingSelection] = []
    for kb_id in kb_ids:
        try:
            kb = await kb_repo.get_knowledge_base(kb_id)
        except NotFoundError as exc:
            raise KnowledgeBaseNotFoundError(str(exc)) from exc
        selections.append(kb.embedding_selection)
    first = selections[0]
    for other in selections[1:]:
        if other != first:
            raise IncompatibleEmbeddingsError(
                "Attached KBs disagree on embedding_selection. "
                f"Got {first.to_dict()} and {other.to_dict()}."
            )
    return first


async def retrieve_docs(
    *,
    tenant_id: UUID,
    qdrant: VectorStorePort,
    dispatcher: EmbedderDispatcherPort,
    kb_repo: KnowledgeBaseRepositoryPort,
    credentials_repo: ProviderCredentialRepositoryPort,
    encryptor: SecretEncryptor,
    ollama_base_url: str,
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
      - RetrievalError if the embedding provider fails (outage/timeout/model
        missing), so the caller surfaces a clean 502 instead of a raw 500.
    """
    if not query.strip():
        return []
    if not kb_ids:
        return []

    selection = await _load_and_validate_kbs(kb_repo, kb_ids)

    provider_id, base_url, api_key = await resolve_inference_target(
        credential_id=selection.credential_id,
        credentials_repo=credentials_repo,
        encryptor=encryptor,
        ollama_base_url=ollama_base_url,
    )
    embedder = dispatcher.for_provider(provider_id)

    # Embedders raise plain RuntimeError on transport/HTTP/model failures.
    # Translate to a domain RetrievalError so the API maps it to 502 (as the
    # LLM path does) rather than letting it escape as an unhandled 500.
    try:
        vectors = await embedder.embed(
            base_url=base_url,
            api_key=api_key,
            model_id=selection.model_id,
            texts=[query],
        )
    except RuntimeError as exc:
        raise RetrievalError(f"Embedding the query failed: {exc}") from exc
    query_vec = vectors[0]

    collection = collection_name_for(tenant_id, selection.dim)
    search_top_k = reranker_initial_top_k if reranker is not None else top_k
    hits = await qdrant.search(
        collection=collection,
        tenant_id=tenant_id,
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
