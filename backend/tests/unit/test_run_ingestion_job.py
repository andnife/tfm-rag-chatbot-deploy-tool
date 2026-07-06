"""Unit tests for the extracted run_ingestion_job use case.

Covers the job state machine (queued -> running -> done | failed), the
missing-entity branches, progress throttling, and the best-effort description
step — using in-memory fakes for the store + the pipeline's seams (no DB, no
Qdrant, no live embedder).
"""
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from tfm_rag.application.knowledge.run_ingestion_job import run_ingestion_job
from tfm_rag.domain.ports.chunker import Chunk
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.model_ref import ModelRef
from tfm_rag.domain.value_objects.retrieval_iteration import LLMTextResponse

pytestmark = pytest.mark.asyncio

_TENANT = uuid4()
_EMB_CRED = uuid4()
_DESC_CRED = uuid4()


class _FakeStore:
    def __init__(
        self,
        *,
        job: object | None,
        source: object | None,
        kb: object | None,
    ) -> None:
        self._job = job
        self._source = source
        self._kb = kb
        self.running: tuple[UUID, UUID] | None = None
        self.done: tuple[UUID, UUID] | None = None
        self.failed: tuple[str, str] | None = None
        self.progress: list[tuple[int, str | None, int | None, int | None]] = []
        self.descriptions: list[str] = []

    async def load_job(self, job_id: UUID) -> object | None:
        return self._job

    async def load_source(self, source_id: UUID) -> object | None:
        return self._source

    async def load_knowledge_base(self, kb_id: UUID) -> object | None:
        return self._kb

    async def mark_running(self, *, job_id: UUID, source_id: UUID) -> None:
        self.running = (job_id, source_id)

    async def update_progress(
        self, *, job_id, progress, stage, items_done, items_total
    ) -> None:  # noqa: ANN001
        self.progress.append((progress, stage, items_done, items_total))

    async def mark_done(self, *, job_id: UUID, source_id: UUID) -> None:
        self.done = (job_id, source_id)

    async def fail_job(self, *, job_id: UUID, error: str) -> None:
        self.failed = ("job", error)

    async def fail_job_and_source(
        self, *, job_id: UUID, source_id: UUID, error: str
    ) -> None:
        self.failed = ("both", error)

    async def set_source_description(
        self, *, source_id: UUID, description: str
    ) -> None:
        self.descriptions.append(description)


def _job(source_id: UUID) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), source_id=source_id)


def _source(kb_id: UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        kb_id=kb_id,
        payload={
            "storage_uri": "file:///x.txt",
            "mime_type": "text/plain",
            "filename": "x.txt",
        },
    )


def _kb(description_llm: ModelRef | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        embedding_selection=EmbeddingSelection(
            credential_id=_EMB_CRED, model_id="bge-m3", dim=1024
        ),
        chunking_config=ChunkingConfig.default(),
        description_llm=description_llm,
    )


async def _resolve_ok(credential_id: UUID) -> tuple[str, str, str | None]:
    return ("ollama", "http://localhost:11434", None)


def _pipeline_doubles(*, chunks: list[Chunk], on_embed_progress: bool = False):
    """Fakes for the seams run_ingestion_pipeline touches."""
    storage = SimpleNamespace()

    async def _load(uri: str) -> bytes:
        return b"raw bytes"

    storage.load = _load

    loader = SimpleNamespace()

    async def _loader_load(raw: bytes) -> str:
        return "hello world"

    loader.load = _loader_load
    dispatcher = SimpleNamespace(for_mime=lambda mime: loader)

    chunker = SimpleNamespace(chunk=lambda text, cfg: chunks)

    class _Embedder:
        async def embed(self, *, texts, on_progress=None, **_kw):  # noqa: ANN001, ANN003
            vecs = []
            for i, _t in enumerate(texts, start=1):
                vecs.append([0.1] * 1024)
                if on_embed_progress and on_progress is not None:
                    await on_progress(i, len(texts))
            return vecs

    embedders = SimpleNamespace(for_provider=lambda pid: _Embedder())

    qdrant = SimpleNamespace()

    async def _upsert(*, collection, points):  # noqa: ANN001, ANN002
        return None

    qdrant.upsert_points = _upsert
    return storage, dispatcher, chunker, embedders, qdrant


def _llms(text: str | None = None) -> SimpleNamespace:
    class _LLM:
        async def generate(self, **_kw: object) -> object:
            return LLMTextResponse(text=text or "A concise summary.")

    return SimpleNamespace(for_provider=lambda pid: _LLM())


async def test_happy_path_marks_running_then_done_and_upserts() -> None:
    kb = _kb()
    source = _source(kb.id)
    job = _job(source.id)
    store = _FakeStore(job=job, source=source, kb=kb)
    storage, dispatcher, chunker, embedders, qdrant = _pipeline_doubles(
        chunks=[Chunk(index=0, text="a", metadata={})]
    )

    await run_ingestion_job(
        job_id=job.id,
        tenant_id=_TENANT,
        jobs=store,  # type: ignore[arg-type]
        resolve_endpoint=_resolve_ok,
        storage=storage,  # type: ignore[arg-type]
        loader_dispatcher=dispatcher,  # type: ignore[arg-type]
        make_chunker=lambda cfg: chunker,  # type: ignore[arg-type]
        embedders=embedders,  # type: ignore[arg-type]
        llms=_llms(),  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    )

    assert store.running == (job.id, source.id)
    assert store.done == (job.id, source.id)
    assert store.failed is None
    # No description_llm configured -> never persisted.
    assert store.descriptions == []


async def test_job_missing_returns_silently() -> None:
    store = _FakeStore(job=None, source=None, kb=None)
    storage, dispatcher, chunker, embedders, qdrant = _pipeline_doubles(chunks=[])

    await run_ingestion_job(
        job_id=uuid4(),
        tenant_id=_TENANT,
        jobs=store,  # type: ignore[arg-type]
        resolve_endpoint=_resolve_ok,
        storage=storage,  # type: ignore[arg-type]
        loader_dispatcher=dispatcher,  # type: ignore[arg-type]
        make_chunker=lambda cfg: chunker,  # type: ignore[arg-type]
        embedders=embedders,  # type: ignore[arg-type]
        llms=_llms(),  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    )

    assert store.running is None
    assert store.done is None
    assert store.failed is None


async def test_source_missing_fails_job_only() -> None:
    job = _job(uuid4())
    store = _FakeStore(job=job, source=None, kb=None)
    storage, dispatcher, chunker, embedders, qdrant = _pipeline_doubles(chunks=[])

    await run_ingestion_job(
        job_id=job.id,
        tenant_id=_TENANT,
        jobs=store,  # type: ignore[arg-type]
        resolve_endpoint=_resolve_ok,
        storage=storage,  # type: ignore[arg-type]
        loader_dispatcher=dispatcher,  # type: ignore[arg-type]
        make_chunker=lambda cfg: chunker,  # type: ignore[arg-type]
        embedders=embedders,  # type: ignore[arg-type]
        llms=_llms(),  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    )

    assert store.failed is not None
    kind, error = store.failed
    assert kind == "job"
    assert "Source not found" in error
    assert store.running is None


async def test_kb_missing_fails_job_only() -> None:
    source = _source(uuid4())
    job = _job(source.id)
    store = _FakeStore(job=job, source=source, kb=None)
    storage, dispatcher, chunker, embedders, qdrant = _pipeline_doubles(chunks=[])

    await run_ingestion_job(
        job_id=job.id,
        tenant_id=_TENANT,
        jobs=store,  # type: ignore[arg-type]
        resolve_endpoint=_resolve_ok,
        storage=storage,  # type: ignore[arg-type]
        loader_dispatcher=dispatcher,  # type: ignore[arg-type]
        make_chunker=lambda cfg: chunker,  # type: ignore[arg-type]
        embedders=embedders,  # type: ignore[arg-type]
        llms=_llms(),  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    )

    assert store.failed is not None
    assert store.failed[0] == "job"
    assert "Knowledge base not found" in store.failed[1]
    assert store.running is None


async def test_endpoint_resolution_failure_fails_job_and_source() -> None:
    kb = _kb()
    source = _source(kb.id)
    job = _job(source.id)
    store = _FakeStore(job=job, source=source, kb=kb)
    storage, dispatcher, chunker, embedders, qdrant = _pipeline_doubles(chunks=[])

    async def _boom(credential_id: UUID) -> tuple[str, str, str | None]:
        raise RuntimeError("credential exploded")

    await run_ingestion_job(
        job_id=job.id,
        tenant_id=_TENANT,
        jobs=store,  # type: ignore[arg-type]
        resolve_endpoint=_boom,
        storage=storage,  # type: ignore[arg-type]
        loader_dispatcher=dispatcher,  # type: ignore[arg-type]
        make_chunker=lambda cfg: chunker,  # type: ignore[arg-type]
        embedders=embedders,  # type: ignore[arg-type]
        llms=_llms(),  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    )

    assert store.failed is not None
    assert store.failed[0] == "both"
    assert "credential exploded" in store.failed[1]
    assert store.running is None  # failed before marking running


async def test_pipeline_error_fails_job_and_source() -> None:
    kb = _kb()
    source = _source(kb.id)
    job = _job(source.id)
    store = _FakeStore(job=job, source=source, kb=kb)
    storage, dispatcher, chunker, embedders, qdrant = _pipeline_doubles(
        chunks=[Chunk(index=0, text="a", metadata={})]
    )

    class _BoomEmbedder:
        async def embed(self, **_kw: object) -> object:
            raise RuntimeError("embedder down")

    embedders = SimpleNamespace(for_provider=lambda pid: _BoomEmbedder())

    await run_ingestion_job(
        job_id=job.id,
        tenant_id=_TENANT,
        jobs=store,  # type: ignore[arg-type]
        resolve_endpoint=_resolve_ok,
        storage=storage,  # type: ignore[arg-type]
        loader_dispatcher=dispatcher,  # type: ignore[arg-type]
        make_chunker=lambda cfg: chunker,  # type: ignore[arg-type]
        embedders=embedders,  # type: ignore[arg-type]
        llms=_llms(),  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    )

    # Marked running (pipeline started) then failed on the embedding step.
    assert store.running == (job.id, source.id)
    assert store.failed is not None
    assert store.failed[0] == "both"
    assert "embedder down" in store.failed[1]
    assert store.done is None


async def test_progress_is_throttled() -> None:
    """Consecutive identical (progress, stage) ticks are collapsed so the DB
    isn't hammered once-per-chunk during embedding."""
    kb = _kb()
    source = _source(kb.id)
    job = _job(source.id)
    store = _FakeStore(job=job, source=source, kb=kb)
    # 100 chunks: the 42->90 embedding ramp rounds many neighbours to the same
    # integer, which the throttle must dedupe.
    chunks = [Chunk(index=i, text=f"c{i}", metadata={}) for i in range(100)]
    storage, dispatcher, chunker, embedders, qdrant = _pipeline_doubles(
        chunks=chunks, on_embed_progress=True
    )

    await run_ingestion_job(
        job_id=job.id,
        tenant_id=_TENANT,
        jobs=store,  # type: ignore[arg-type]
        resolve_endpoint=_resolve_ok,
        storage=storage,  # type: ignore[arg-type]
        loader_dispatcher=dispatcher,  # type: ignore[arg-type]
        make_chunker=lambda cfg: chunker,  # type: ignore[arg-type]
        embedders=embedders,  # type: ignore[arg-type]
        llms=_llms(),  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    )

    assert store.done == (job.id, source.id)
    embedding = [(p, stage) for (p, stage, _d, _t) in store.progress if stage == "embedding"]
    # Fewer persisted ticks than chunks (throttling did collapse some) ...
    assert len(embedding) < 100
    # ... and no two CONSECUTIVE embedding ticks share the same (progress,stage).
    for a, b in zip(embedding, embedding[1:], strict=False):
        assert a != b


async def test_description_generated_and_persisted() -> None:
    kb = _kb(description_llm=ModelRef(credential_id=_DESC_CRED, model_id="gpt"))
    source = _source(kb.id)
    job = _job(source.id)
    store = _FakeStore(job=job, source=source, kb=kb)
    storage, dispatcher, chunker, embedders, qdrant = _pipeline_doubles(
        chunks=[Chunk(index=0, text="a", metadata={})]
    )

    await run_ingestion_job(
        job_id=job.id,
        tenant_id=_TENANT,
        jobs=store,  # type: ignore[arg-type]
        resolve_endpoint=_resolve_ok,
        storage=storage,  # type: ignore[arg-type]
        loader_dispatcher=dispatcher,  # type: ignore[arg-type]
        make_chunker=lambda cfg: chunker,  # type: ignore[arg-type]
        embedders=embedders,  # type: ignore[arg-type]
        llms=_llms(text="A concise summary."),  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    )

    assert store.done == (job.id, source.id)
    assert store.descriptions == ["A concise summary."]


async def test_description_skipped_when_credential_unresolvable() -> None:
    kb = _kb(description_llm=ModelRef(credential_id=_DESC_CRED, model_id="gpt"))
    source = _source(kb.id)
    job = _job(source.id)
    store = _FakeStore(job=job, source=source, kb=kb)
    storage, dispatcher, chunker, embedders, qdrant = _pipeline_doubles(
        chunks=[Chunk(index=0, text="a", metadata={})]
    )

    async def _resolve(credential_id: UUID) -> tuple[str, str, str | None]:
        if credential_id == _DESC_CRED:
            raise RuntimeError("description credential gone")
        return ("ollama", "http://localhost:11434", None)

    await run_ingestion_job(
        job_id=job.id,
        tenant_id=_TENANT,
        jobs=store,  # type: ignore[arg-type]
        resolve_endpoint=_resolve,
        storage=storage,  # type: ignore[arg-type]
        loader_dispatcher=dispatcher,  # type: ignore[arg-type]
        make_chunker=lambda cfg: chunker,  # type: ignore[arg-type]
        embedders=embedders,  # type: ignore[arg-type]
        llms=_llms(),  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    )

    # Ingestion still completes; description generation is best-effort.
    assert store.done == (job.id, source.id)
    assert store.descriptions == []
