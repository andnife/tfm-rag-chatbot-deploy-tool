from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid5

from tfm_rag.domain.ports.chunker import Chunker
from tfm_rag.domain.ports.embedder import Embedder
from tfm_rag.domain.ports.storage import Storage
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.infrastructure.document_loaders.dispatcher import LoaderDispatcher
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore

ProgressCallback = Callable[[int], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class IngestionContext:
    tenant_id: UUID
    kb_id: UUID
    source_id: UUID
    storage_uri: str
    mime_type: str
    filename: str
    chunking_config: ChunkingConfig
    embedding_selection: EmbeddingSelection
    embedder_base_url: str
    embedder_api_key: str | None
    collection: str


def _point_id(source_id: UUID, chunk_index: int) -> str:
    """Deterministic UUIDv5 so reindex overwrites the same Qdrant points.

    Uses the source_id itself as the uuid5 namespace; same (source_id,
    chunk_index) always produces the same id.
    """
    return str(uuid5(source_id, f"chunk-{chunk_index}"))


async def run_ingestion_pipeline(
    ctx: IngestionContext,
    *,
    storage: Storage,
    loader_dispatcher: LoaderDispatcher,
    chunker: Chunker,
    embedder: Embedder,
    qdrant: QdrantStore,
    on_progress: ProgressCallback,
) -> None:
    await on_progress(5)

    raw = await storage.load(ctx.storage_uri)
    await on_progress(15)

    loader = loader_dispatcher.for_mime(ctx.mime_type)
    text = await loader.load(raw)
    await on_progress(35)

    chunks = chunker.chunk(text, ctx.chunking_config)
    await on_progress(50)
    if not chunks:
        await on_progress(100)
        return

    vectors = await embedder.embed(
        base_url=ctx.embedder_base_url,
        api_key=ctx.embedder_api_key,
        model_id=ctx.embedding_selection.model_id,
        texts=[c.text for c in chunks],
    )
    await on_progress(85)

    points: list[tuple[str, list[float], dict[str, Any]]] = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        payload: dict[str, Any] = {
            "tenant_id": str(ctx.tenant_id),
            "kb_id": str(ctx.kb_id),
            "source_id": str(ctx.source_id),
            "chunk_index": chunk.index,
            "content": chunk.text,
            "source_filename": ctx.filename,
            **chunk.metadata,
        }
        points.append((_point_id(ctx.source_id, chunk.index), vector, payload))

    await qdrant.upsert_points(collection=ctx.collection, points=points)
    await on_progress(100)
