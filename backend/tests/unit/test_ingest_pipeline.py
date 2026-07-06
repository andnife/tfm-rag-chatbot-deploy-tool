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

    async def on_progress(p: int, **_kw: object) -> None:
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
        on_progress=lambda _p, **_kw: _noop(),
    )

    chunker.chunk.assert_called_once()
    embedder.embed.assert_not_awaited()
    qdrant.upsert_points.assert_not_awaited()


async def _noop() -> None:
    return None


def _full_doubles() -> dict:
    storage = MagicMock()
    storage.load = AsyncMock(return_value=b"hello world")
    loader = MagicMock()
    loader.load = AsyncMock(return_value="hello world")
    dispatcher = MagicMock()
    dispatcher.for_mime = MagicMock(return_value=loader)
    chunker = MagicMock()
    chunker.chunk = MagicMock(
        return_value=[Chunk(index=0, text="hello", metadata={})]
    )
    embedder = MagicMock()
    embedder.embed = AsyncMock(return_value=[[0.1] * 1024])
    qdrant = MagicMock()
    qdrant.upsert_points = AsyncMock()
    return {
        "storage": storage, "loader_dispatcher": dispatcher,
        "chunker": chunker, "embedder": embedder, "qdrant": qdrant,
    }


def _ctx() -> IngestionContext:
    return IngestionContext(
        tenant_id=uuid4(), kb_id=uuid4(), source_id=uuid4(),
        storage_uri="file:///tmp/x.txt", mime_type="text/plain",
        filename="x.txt", chunking_config=ChunkingConfig.default(),
        embedding_selection=_selection(),
        embedder_base_url="http://localhost:11434", embedder_api_key=None,
        collection="kb_chunks__t__1024",
    )


@pytest.mark.asyncio
async def test_pipeline_generates_and_saves_description() -> None:
    doubles = _full_doubles()
    saved: list[str] = []

    async def describe_fn(chunks: list[Chunk]) -> str | None:
        return f"desc for {len(chunks)} chunks"

    async def save_description(text: str) -> None:
        saved.append(text)

    await run_ingestion_pipeline(
        _ctx(), on_progress=lambda _p, **_kw: _noop(),
        describe_fn=describe_fn, save_description=save_description, **doubles,
    )
    assert saved == ["desc for 1 chunks"]


@pytest.mark.asyncio
async def test_pipeline_skips_save_when_description_is_none() -> None:
    doubles = _full_doubles()
    saved: list[str] = []

    async def describe_fn(chunks: list[Chunk]) -> str | None:
        return None

    async def save_description(text: str) -> None:
        saved.append(text)

    await run_ingestion_pipeline(
        _ctx(), on_progress=lambda _p, **_kw: _noop(),
        describe_fn=describe_fn, save_description=save_description, **doubles,
    )
    assert saved == []


@pytest.mark.asyncio
async def test_pipeline_survives_describe_fn_error() -> None:
    doubles = _full_doubles()
    saved: list[str] = []

    async def describe_fn(chunks: list[Chunk]) -> str | None:
        raise RuntimeError("llm down")

    async def save_description(text: str) -> None:
        saved.append(text)

    # Must not raise; ingestion completed (upsert happened), no description saved.
    await run_ingestion_pipeline(
        _ctx(), on_progress=lambda _p, **_kw: _noop(),
        describe_fn=describe_fn, save_description=save_description, **doubles,
    )
    assert saved == []
    doubles["qdrant"].upsert_points.assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_reports_stage_and_embedding_ramp() -> None:
    """Captures every on_progress call to verify phases + per-chunk ramp."""
    chunks = [Chunk(index=i, text=f"c{i}", metadata={}) for i in range(4)]

    class _FakeEmbedder:
        async def embed(self, *, texts, on_progress=None, **_kw):  # noqa: ANN001, ANN003
            vecs = []
            for i, _t in enumerate(texts, start=1):
                vecs.append([0.1] * 1024)
                if on_progress is not None:
                    await on_progress(i, len(texts))
            return vecs

    storage = MagicMock()
    storage.load = AsyncMock(return_value=b"hello world")
    loader = MagicMock()
    loader.load = AsyncMock(return_value="hello world")
    dispatcher = MagicMock()
    dispatcher.for_mime = MagicMock(return_value=loader)
    chunker = MagicMock()
    chunker.chunk = MagicMock(return_value=chunks)
    qdrant = MagicMock()
    qdrant.upsert_points = AsyncMock()

    events: list[tuple[int, str | None, int | None, int | None]] = []

    async def on_progress(
        p: int,
        *,
        stage: str | None = None,
        items_done: int | None = None,
        items_total: int | None = None,
    ) -> None:
        events.append((p, stage, items_done, items_total))

    await run_ingestion_pipeline(
        _ctx(),
        storage=storage,
        loader_dispatcher=dispatcher,
        chunker=chunker,
        embedder=_FakeEmbedder(),
        qdrant=qdrant,
        on_progress=on_progress,
    )

    stages = [stage for _p, stage, _d, _t in events]
    assert "extracting" in stages
    assert "chunking" in stages
    assert "indexing" in stages

    embedding = [(p, d, t) for p, stage, d, t in events if stage == "embedding"]
    # One per chunk, items_done 1..4, items_total 4, progress monotonic in [42,90]
    assert [d for _p, d, _t in embedding] == [1, 2, 3, 4]
    assert all(t == 4 for _p, _d, t in embedding)
    assert all(42 <= p <= 90 for p, _d, _t in embedding)
    assert embedding == sorted(embedding)
    assert events[-1][0] == 100
