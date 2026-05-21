from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from tfm_rag.application.knowledge.ingest_source import (
    IngestionContext,
    run_ingestion_pipeline,
)
from tfm_rag.domain.ports.chunker import Chunk
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection


def _selection(credential_id: UUID | None = None) -> EmbeddingSelection:
    return EmbeddingSelection(
        provider_id="ollama",
        credential_id=credential_id or uuid4(),
        model_id="bge-m3",
        dim=1024,
    )


@pytest.mark.asyncio
async def test_pipeline_loads_chunks_embeds_and_upserts() -> None:
    tenant_id = uuid4()
    kb_id = uuid4()
    source_id = uuid4()
    storage = MagicMock()
    storage.load = AsyncMock(return_value=b"hello world")
    loader = MagicMock()
    loader.load = AsyncMock(return_value="hello world")
    dispatcher = MagicMock()
    dispatcher.for_mime = MagicMock(return_value=loader)
    chunker = MagicMock()
    chunker.chunk = MagicMock(
        return_value=[
            Chunk(index=0, text="hello", metadata={"chunk_start": 0}),
            Chunk(index=1, text="world", metadata={"chunk_start": 6}),
        ]
    )
    embedder = MagicMock()
    embedder.embed = AsyncMock(
        return_value=[[0.1] * 1024, [0.2] * 1024]
    )
    qdrant = MagicMock()
    qdrant.upsert_points = AsyncMock()
    progress_updates: list[int] = []

    async def on_progress(p: int) -> None:
        progress_updates.append(p)

    ctx = IngestionContext(
        tenant_id=tenant_id,
        kb_id=kb_id,
        source_id=source_id,
        storage_uri="file:///tmp/x.txt",
        mime_type="text/plain",
        filename="x.txt",
        chunking_config=ChunkingConfig.default(),
        embedding_selection=_selection(),
        embedder_base_url="http://localhost:11434",
        embedder_api_key=None,
        collection="kb_chunks__t__1024",
    )

    await run_ingestion_pipeline(
        ctx,
        storage=storage,
        loader_dispatcher=dispatcher,
        chunker=chunker,
        embedder=embedder,
        qdrant=qdrant,
        on_progress=on_progress,
    )

    storage.load.assert_awaited_once_with("file:///tmp/x.txt")
    dispatcher.for_mime.assert_called_once_with("text/plain")
    loader.load.assert_awaited_once_with(b"hello world")
    chunker.chunk.assert_called_once()
    embedder.embed.assert_awaited_once()
    qdrant.upsert_points.assert_awaited_once()
    # Verify the upsert payload structure
    call_kwargs = qdrant.upsert_points.await_args.kwargs
    points = call_kwargs["points"]
    assert len(points) == 2
    pid0, vec0, payload0 = points[0]
    assert payload0["tenant_id"] == str(tenant_id)
    assert payload0["kb_id"] == str(kb_id)
    assert payload0["source_id"] == str(source_id)
    assert payload0["chunk_index"] == 0
    assert payload0["content"] == "hello"
    assert len(vec0) == 1024
    # Progress was reported at least at intake (>=0) and completion (100)
    assert 100 in progress_updates


@pytest.mark.asyncio
async def test_pipeline_with_empty_text_makes_no_qdrant_call() -> None:
    storage = MagicMock()
    storage.load = AsyncMock(return_value=b"   ")
    loader = MagicMock()
    loader.load = AsyncMock(return_value="   ")
    dispatcher = MagicMock()
    dispatcher.for_mime = MagicMock(return_value=loader)
    chunker = MagicMock()
    chunker.chunk = MagicMock(return_value=[])
    embedder = MagicMock()
    embedder.embed = AsyncMock(return_value=[])
    qdrant = MagicMock()
    qdrant.upsert_points = AsyncMock()

    ctx = IngestionContext(
        tenant_id=uuid4(),
        kb_id=uuid4(),
        source_id=uuid4(),
        storage_uri="file:///tmp/y.txt",
        mime_type="text/plain",
        filename="y.txt",
        chunking_config=ChunkingConfig.default(),
        embedding_selection=_selection(),
        embedder_base_url="http://localhost:11434",
        embedder_api_key=None,
        collection="kb_chunks__t__1024",
    )

    await run_ingestion_pipeline(
        ctx,
        storage=storage,
        loader_dispatcher=dispatcher,
        chunker=chunker,
        embedder=embedder,
        qdrant=qdrant,
        on_progress=lambda _p: _noop(),
    )

    chunker.chunk.assert_called_once()
    embedder.embed.assert_not_awaited()
    qdrant.upsert_points.assert_not_awaited()


async def _noop() -> None:
    return None
