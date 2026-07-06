from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid5

from tfm_rag.domain.ports.chunker import Chunk, Chunker
from tfm_rag.domain.ports.document_loader import LoaderDispatcherPort
from tfm_rag.domain.ports.embedder import Embedder
from tfm_rag.domain.ports.storage import Storage
from tfm_rag.domain.ports.vector_store import VectorStorePort
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection

# on_progress(progress: int, *, stage: str | None = None,
#             items_done: int | None = None, items_total: int | None = None)
ProgressCallback = Callable[..., Awaitable[None]]

# Qdrant upsert is chunked into batches so the indexing phase (90→100 %) ramps
# instead of jumping. 64 points/batch keeps payloads small without many calls.
_UPSERT_BATCH = 64


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
    loader_dispatcher: LoaderDispatcherPort,
    chunker: Chunker,
    embedder: Embedder,
    qdrant: VectorStorePort,
    on_progress: ProgressCallback,
    describe_fn: Callable[[list[Chunk]], Awaitable[str | None]] | None = None,
    save_description: Callable[[str], Awaitable[None]] | None = None,
) -> None:
    # Phase 1 (uploading 0–25 %) is owned by the frontend (XHR bytes); the job
    # picks up at extracting. Setting the stage immediately lifts the bar to the
    # extracting band start so it doesn't drop back to 0 after the upload.
    await on_progress(25, stage="extracting")

    raw = await storage.load(ctx.storage_uri)
    loader = loader_dispatcher.for_mime(ctx.mime_type)
    text = await loader.load(raw)

    await on_progress(35, stage="chunking")
    chunks = chunker.chunk(text, ctx.chunking_config)
    if not chunks:
        await on_progress(100)
        return

    total = len(chunks)

    async def _emb_progress(done: int, _total: int) -> None:
        await on_progress(
            42 + round(48 * done / total),
            stage="embedding",
            items_done=done,
            items_total=total,
        )

    vectors = await embedder.embed(
        base_url=ctx.embedder_base_url,
        api_key=ctx.embedder_api_key,
        model_id=ctx.embedding_selection.model_id,
        texts=[c.text for c in chunks],
        on_progress=_emb_progress,
    )

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

    n = len(points)
    for i in range(0, n, _UPSERT_BATCH):
        await qdrant.upsert_points(
            collection=ctx.collection, points=points[i : i + _UPSERT_BATCH]
        )
        done = min(i + _UPSERT_BATCH, n)
        await on_progress(
            90 + round(10 * done / n),
            stage="indexing",
            items_done=done,
            items_total=n,
        )

    if describe_fn is not None and save_description is not None:
        try:
            description = await describe_fn(chunks)
        except Exception:  # noqa: BLE001 - best-effort enrichment, never fail ingestion
            description = None
        if description:
            await save_description(description)

    await on_progress(100)
