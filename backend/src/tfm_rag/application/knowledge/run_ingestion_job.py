"""run_ingestion_job — background orchestration for a single document ingest.

Extracted verbatim (behaviour-preserving) from the former
``_ingest_in_background`` router closure. Depends only on ports + injected
callables; the router composes the concrete adapters and owns the Qdrant
client lifecycle.

State transitions (queued -> running -> done | failed) and progress ticks go
through an ``IngestionJobStorePort`` whose methods each commit their own unit
of work, so a concurrent status poller observes every transition.
"""
from collections.abc import Awaitable, Callable
from uuid import UUID

from tfm_rag.application.knowledge.describe_document import describe_document
from tfm_rag.application.knowledge.ingest_source import (
    IngestionContext,
    run_ingestion_pipeline,
)
from tfm_rag.domain.ports.chunker import Chunk, Chunker
from tfm_rag.domain.ports.document_loader import LoaderDispatcherPort
from tfm_rag.domain.ports.embedder import EmbedderDispatcherPort
from tfm_rag.domain.ports.llm import LLMDispatcherPort
from tfm_rag.domain.ports.repositories import IngestionJobStorePort
from tfm_rag.domain.ports.storage import Storage
from tfm_rag.domain.ports.vector_store import VectorStorePort
from tfm_rag.domain.services.collection_naming import collection_name_for
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig

# Resolve a credential to (provider_id, base_url, api_key). Injected by the
# edge so the use case never touches credentials/encryptor/session.
EndpointResolver = Callable[[UUID], Awaitable[tuple[str, str, str | None]]]


async def run_ingestion_job(
    *,
    job_id: UUID,
    tenant_id: UUID,
    jobs: IngestionJobStorePort,
    resolve_endpoint: EndpointResolver,
    storage: Storage,
    loader_dispatcher: LoaderDispatcherPort,
    make_chunker: Callable[[ChunkingConfig], Chunker],
    embedders: EmbedderDispatcherPort,
    llms: LLMDispatcherPort,
    qdrant: VectorStorePort,
) -> None:
    """Never raises — failures are written to the job/source rows."""
    job = await jobs.load_job(job_id)
    if job is None:
        return  # Job was deleted or tenant mismatch — abort silently.

    source = await jobs.load_source(job.source_id)
    if source is None:
        await jobs.fail_job(
            job_id=job_id, error="Source not found (may have been deleted)"
        )
        return

    kb = await jobs.load_knowledge_base(source.kb_id)
    if kb is None:
        await jobs.fail_job(
            job_id=job_id,
            error="Knowledge base not found (may have been deleted)",
        )
        return

    try:
        emb_provider_id, emb_base_url, emb_api_key = await resolve_endpoint(
            kb.embedding_selection.credential_id
        )
    except Exception as exc:  # noqa: BLE001
        await jobs.fail_job_and_source(
            job_id=job_id, source_id=source.id, error=str(exc)
        )
        return

    ctx = IngestionContext(
        tenant_id=tenant_id,
        kb_id=kb.id,
        source_id=source.id,
        storage_uri=source.payload["storage_uri"],
        mime_type=source.payload["mime_type"],
        filename=source.payload["filename"],
        chunking_config=kb.chunking_config,
        embedding_selection=kb.embedding_selection,
        embedder_base_url=emb_base_url,
        embedder_api_key=emb_api_key,
        collection=collection_name_for(tenant_id, kb.embedding_selection.dim),
    )

    await jobs.mark_running(job_id=job_id, source_id=source.id)

    # Throttle DB writes: the embedding phase fires on_progress once per chunk
    # (could be hundreds). Only persist when the integer progress OR the stage
    # changes — caps writes at a few dozen per document while the 2s frontend
    # poll never sees the missing sub-steps.
    last_progress = -1
    last_stage: str | None = None

    async def _on_progress(
        p: int,
        *,
        stage: str | None = None,
        items_done: int | None = None,
        items_total: int | None = None,
    ) -> None:
        nonlocal last_progress, last_stage
        if p == last_progress and stage == last_stage:
            return
        last_progress = p
        last_stage = stage
        await jobs.update_progress(
            job_id=job_id,
            progress=p,
            stage=stage,
            items_done=items_done,
            items_total=items_total,
        )

    # C1: generate a per-document description (best-effort) using the KB's
    # optional `description_llm`. When it is unset or its credential fails to
    # resolve, description generation is skipped and the caller falls back to
    # the filename (graceful degradation — never blocks ingestion).
    describe_fn: Callable[[list[Chunk]], Awaitable[str | None]] | None = None
    save_description: Callable[[str], Awaitable[None]] | None = None
    if kb.description_llm is not None:
        desc_target: tuple[str, str, str | None] | None
        try:
            desc_target = await resolve_endpoint(
                kb.description_llm.credential_id
            )
        except Exception:  # noqa: BLE001 - best-effort, never blocks ingestion
            desc_target = None
        if desc_target is not None:
            desc_provider_id, desc_base_url, desc_api_key = desc_target
            desc_llm = llms.for_provider(desc_provider_id)
            desc_model = kb.description_llm.model_id
            src_id = source.id

            async def _make_description(chunks: list[Chunk]) -> str | None:
                return await describe_document(
                    chunks,
                    llm=desc_llm,
                    base_url=desc_base_url,
                    api_key=desc_api_key,
                    model_id=desc_model,
                )

            async def _persist_description(text: str) -> None:
                await jobs.set_source_description(
                    source_id=src_id, description=text
                )

            describe_fn = _make_description
            save_description = _persist_description

    try:
        await run_ingestion_pipeline(
            ctx,
            storage=storage,
            loader_dispatcher=loader_dispatcher,
            chunker=make_chunker(kb.chunking_config),
            embedder=embedders.for_provider(emb_provider_id),
            qdrant=qdrant,
            on_progress=_on_progress,
            describe_fn=describe_fn,
            save_description=save_description,
        )
    except Exception as exc:  # noqa: BLE001
        await jobs.fail_job_and_source(
            job_id=job_id, source_id=source.id, error=str(exc)
        )
        return

    await jobs.mark_done(job_id=job_id, source_id=source.id)
