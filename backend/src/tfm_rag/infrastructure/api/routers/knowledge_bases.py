from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tfm_rag.application.knowledge.attach_document_source import (
    attach_document_source,
)
from tfm_rag.application.knowledge.create_knowledge_base import (
    KnowledgeBaseView,
    create_knowledge_base,
)
from tfm_rag.application.knowledge.delete_knowledge_base import (
    delete_knowledge_base,
)
from tfm_rag.application.knowledge.detach_source import detach_source
from tfm_rag.application.knowledge.get_knowledge_base import get_knowledge_base
from tfm_rag.application.knowledge.ingest_source import (
    IngestionContext,
    run_ingestion_pipeline,
)
from tfm_rag.application.knowledge.list_knowledge_bases import (
    list_knowledge_bases,
)
from tfm_rag.application.knowledge.list_sources import list_sources
from tfm_rag.application.knowledge.reindex_source import purge_source_chunks
from tfm_rag.application.knowledge.test_source_connection import (
    test_source_connection,
)
from tfm_rag.application.knowledge.update_knowledge_base import (
    update_knowledge_base,
)
from tfm_rag.domain.entities.source import SourceType
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.errors.knowledge import (
    KnowledgeBaseInUseError,
    KnowledgeBaseNotFoundError,
    SourceNotFoundError,
)
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.infrastructure.api.dependencies import (
    get_current_context,
    get_session,
    get_session_factory,  # noqa: PLC2701
)
from tfm_rag.infrastructure.chunkers.fixed_size import FixedSizeChunker
from tfm_rag.infrastructure.document_loaders.dispatcher import LoaderDispatcher
from tfm_rag.infrastructure.document_loaders.pdf import PdfLoader
from tfm_rag.infrastructure.document_loaders.txt import TxtLoader
from tfm_rag.infrastructure.embedders.ollama import OllamaEmbedder
from tfm_rag.infrastructure.jobs.runner import JobsRunner
from tfm_rag.infrastructure.persistence.models.ingestion_jobs import (
    IngestionJobRow,
)
from tfm_rag.infrastructure.persistence.models.knowledge_bases import (
    KnowledgeBaseRow,
)
from tfm_rag.infrastructure.persistence.models.sources import SourceRow
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.settings import Settings, get_settings
from tfm_rag.infrastructure.storage.local import LocalStorage
from tfm_rag.infrastructure.vector_store.qdrant_client import (
    QdrantStore,
    collection_name_for,
)

router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge"])

_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


class ChunkingConfigIn(BaseModel):
    strategy: Literal["recursive", "by_paragraph", "fixed"] = "recursive"
    chunk_size: int = Field(default=1000, ge=100, le=4000)
    chunk_overlap: int = Field(default=200, ge=0, le=500)

    def to_vo(self) -> ChunkingConfig:
        return ChunkingConfig(
            strategy=self.strategy,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )


class EmbeddingSelectionIn(BaseModel):
    provider_id: str
    credential_id: UUID
    model_id: str
    dim: int

    def to_vo(self) -> EmbeddingSelection:
        return EmbeddingSelection(
            provider_id=self.provider_id,
            credential_id=self.credential_id,
            model_id=self.model_id,
            dim=self.dim,
        )


class CreateKbIn(BaseModel):
    name: str
    description: str | None = None
    chunking_config: ChunkingConfigIn = Field(default_factory=ChunkingConfigIn)
    embedding_selection: EmbeddingSelectionIn


class UpdateKbIn(BaseModel):
    name: str | None = None
    description: str | None = None
    chunking_config: ChunkingConfigIn | None = None
    embedding_selection: EmbeddingSelectionIn | None = None


class KbOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: str | None
    chunking_config: dict[str, Any]
    embedding_selection: dict[str, Any]

    @classmethod
    def from_view(cls, v: KnowledgeBaseView) -> "KbOut":
        return cls(
            id=str(v.id),
            tenant_id=str(v.tenant_id),
            name=v.name,
            description=v.description,
            chunking_config=v.chunking_config.to_dict(),
            embedding_selection=v.embedding_selection.to_dict(),
        )


class SourceOut(BaseModel):
    id: str
    kb_id: str
    type: SourceType
    ingest_status: str


class KbDetailOut(BaseModel):
    kb: KbOut
    sources: list[SourceOut]


class UpdateKbOut(BaseModel):
    kb: KbOut
    reindex_required: bool


class TestConnectionIn(BaseModel):
    type: SourceType
    spec: dict[str, Any]


def _qdrant(settings: Settings) -> QdrantStore:
    return QdrantStore(settings.qdrant_url, settings.qdrant_api_key)


@router.post("", status_code=201, response_model=KbOut)
async def create_(
    body: CreateKbIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> KbOut:
    qdrant = _qdrant(settings)
    try:
        view = await create_knowledge_base(
            session,
            ctx,
            qdrant,
            name=body.name,
            description=body.description,
            chunking_config=body.chunking_config.to_vo(),
            embedding_selection=body.embedding_selection.to_vo(),
        )
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        await qdrant.close()
    return KbOut.from_view(view)


@router.get("", response_model=list[KbOut])
async def list_(
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> list[KbOut]:
    views = await list_knowledge_bases(session, ctx, limit=limit, offset=offset)
    return [KbOut.from_view(v) for v in views]


@router.get("/{kb_id}", response_model=KbDetailOut)
async def get_(
    kb_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> KbDetailOut:
    try:
        detail = await get_knowledge_base(session, ctx, kb_id=kb_id)
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return KbDetailOut(
        kb=KbOut.from_view(detail.kb),
        sources=[
            SourceOut(
                id=str(s.id),
                kb_id=str(s.kb_id),
                type=s.type,
                ingest_status=s.ingest_status,
            )
            for s in detail.sources
        ],
    )


@router.patch("/{kb_id}", response_model=UpdateKbOut)
async def patch_(
    kb_id: UUID,
    body: UpdateKbIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> UpdateKbOut:
    qdrant = _qdrant(settings)
    try:
        result = await update_knowledge_base(
            session,
            ctx,
            qdrant,
            kb_id=kb_id,
            name=body.name,
            description=body.description,
            chunking_config=(
                body.chunking_config.to_vo() if body.chunking_config else None
            ),
            embedding_selection=(
                body.embedding_selection.to_vo()
                if body.embedding_selection
                else None
            ),
        )
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        await qdrant.close()
    return UpdateKbOut(
        kb=KbOut.from_view(result.kb),
        reindex_required=result.reindex_required,
    )


@router.delete("/{kb_id}", status_code=204)
async def delete_(
    kb_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> None:
    try:
        await delete_knowledge_base(session, ctx, kb_id=kb_id)
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except KnowledgeBaseInUseError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{kb_id}/sources", response_model=list[SourceOut])
async def list_sources_(
    kb_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> list[SourceOut]:
    try:
        views = await list_sources(session, ctx, kb_id=kb_id)
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [
        SourceOut(
            id=str(s.id),
            kb_id=str(s.kb_id),
            type=s.type,
            ingest_status=s.ingest_status,
        )
        for s in views
    ]


@router.delete("/{kb_id}/sources/{source_id}", status_code=204)
async def detach_source_(
    kb_id: UUID,
    source_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> None:
    try:
        await detach_source(session, ctx, kb_id=kb_id, source_id=source_id)
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SourceNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{kb_id}/sources/test-connection")
async def test_connection_(
    kb_id: UUID,
    body: TestConnectionIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> dict[str, Any]:
    # Validate that the KB exists and belongs to the tenant before testing.
    try:
        await get_knowledge_base(session, ctx, kb_id=kb_id)
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    result = await test_source_connection(spec_type=body.type, spec=body.spec)
    return {"ok": result.ok, "error": result.error, "details": result.details}


def _storage(settings: Settings) -> LocalStorage:
    return LocalStorage(root=settings.storage_local_path)


def _loader_dispatcher() -> LoaderDispatcher:
    return LoaderDispatcher([PdfLoader(), TxtLoader()])


async def _ingest_in_background(
    *,
    factory: async_sessionmaker[AsyncSession],
    qdrant_url: str,
    qdrant_api_key: str | None,
    settings: Settings,
    job_id: UUID,
    tenant_id: UUID,
) -> None:
    """Background pipeline. Opens its own session and Qdrant client.

    Updates `ingestion_jobs.status/progress/error/finished_at` as the pipeline
    progresses. Never raises — failures are written to the row.
    """
    qdrant = QdrantStore(url=qdrant_url, api_key=qdrant_api_key)
    try:
        async with factory() as session:
            # Load job + source + KB
            job = (await session.execute(
                select(IngestionJobRow).where(
                    IngestionJobRow.id == job_id,
                    IngestionJobRow.tenant_id == tenant_id,
                )
            )).scalar_one_or_none()
            if job is None:
                return  # Job was deleted or tenant mismatch — abort silently.

            source = (await session.execute(
                select(SourceRow).where(SourceRow.id == job.source_id)
            )).scalar_one_or_none()
            if source is None:
                async with factory() as s_err:
                    await s_err.execute(
                        update(IngestionJobRow)
                        .where(IngestionJobRow.id == job_id)
                        .values(
                            status="failed",
                            error="Source not found (may have been deleted)",
                            finished_at=datetime.now(UTC),
                        )
                    )
                    await s_err.commit()
                return

            kb = (await session.execute(
                select(KnowledgeBaseRow).where(
                    KnowledgeBaseRow.id == source.kb_id,
                    KnowledgeBaseRow.tenant_id == tenant_id,
                )
            )).scalar_one_or_none()
            if kb is None:
                async with factory() as s_err:
                    await s_err.execute(
                        update(IngestionJobRow)
                        .where(IngestionJobRow.id == job_id)
                        .values(
                            status="failed",
                            error="Knowledge base not found (may have been deleted)",
                            finished_at=datetime.now(UTC),
                        )
                    )
                    await s_err.commit()
                return

            chunking = ChunkingConfig.from_dict(kb.chunking_config)
            selection = EmbeddingSelection.from_dict(kb.embedding_selection)
            collection = collection_name_for(tenant_id, selection.dim)

            payload = source.payload
            ctx = IngestionContext(
                tenant_id=tenant_id,
                kb_id=kb.id,
                source_id=source.id,
                storage_uri=payload["storage_uri"],
                mime_type=payload["mime_type"],
                filename=payload["filename"],
                chunking_config=chunking,
                embedding_selection=selection,
                embedder_base_url=settings.ollama_base_url,
                embedder_api_key=None,  # Ollama is keyless in M2
                collection=collection,
            )

            # Mark as running
            job.status = "running"
            job.progress = 0
            source.ingest_status = "running"
            await session.commit()

            async def _on_progress(p: int) -> None:
                async with factory() as s2:
                    await s2.execute(
                        update(IngestionJobRow)
                        .where(IngestionJobRow.id == job_id)
                        .values(progress=p)
                    )
                    await s2.commit()

            try:
                await run_ingestion_pipeline(
                    ctx,
                    storage=_storage(settings),
                    loader_dispatcher=_loader_dispatcher(),
                    chunker=FixedSizeChunker(),
                    embedder=OllamaEmbedder(),
                    qdrant=qdrant,
                    on_progress=_on_progress,
                )
            except Exception as exc:  # noqa: BLE001
                async with factory() as s3:
                    await s3.execute(
                        update(IngestionJobRow)
                        .where(IngestionJobRow.id == job_id)
                        .values(
                            status="failed",
                            error=str(exc)[:1900],
                            finished_at=datetime.now(UTC),
                        )
                    )
                    await s3.execute(
                        update(SourceRow)
                        .where(SourceRow.id == source.id)
                        .values(
                            ingest_status="failed",
                            error=str(exc)[:1900],
                        )
                    )
                    await s3.commit()
                return

            # Success
            async with factory() as s4:
                now = datetime.now(UTC)
                await s4.execute(
                    update(IngestionJobRow)
                    .where(IngestionJobRow.id == job_id)
                    .values(
                        status="done",
                        progress=100,
                        finished_at=now,
                    )
                )
                await s4.execute(
                    update(SourceRow)
                    .where(SourceRow.id == source.id)
                    .values(
                        ingest_status="done",
                        last_ingest_at=now,
                        error=None,
                    )
                )
                await s4.commit()
    finally:
        await qdrant.close()


class UploadDocOut(BaseModel):
    source_id: str
    job_id: str


@router.post(
    "/{kb_id}/sources/documents",
    status_code=201,
    response_model=UploadDocOut,
)
async def upload_document_(
    kb_id: UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),  # noqa: B008
    filename: str | None = Form(default=None),
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> UploadDocOut:
    content = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large: max {_MAX_UPLOAD_BYTES // (1024*1024)} MB",
        )
    name = filename or file.filename or "document"
    mime = file.content_type or "application/octet-stream"
    try:
        result = await attach_document_source(
            session,
            ctx,
            _storage(settings),
            kb_id=kb_id,
            filename=name,
            mime_type=mime,
            content=content,
        )
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Create the IngestionJob row in the same session
    job_id = uuid4()
    session.add(
        IngestionJobRow(
            id=job_id,
            source_id=result.source_id,
            tenant_id=ctx.tenant_id,
            status="queued",
            progress=0,
        )
    )
    # Commit explicitly so the background task can read the row via a new session.
    # get_session will call commit() again on the already-clean session (no-op).
    await session.commit()

    factory = get_session_factory(settings)
    runner = JobsRunner(background_tasks)

    async def _kick() -> None:
        await _ingest_in_background(
            factory=factory,
            qdrant_url=settings.qdrant_url,
            qdrant_api_key=settings.qdrant_api_key,
            settings=settings,
            job_id=job_id,
            tenant_id=ctx.tenant_id,
        )

    runner.schedule(_kick)

    return UploadDocOut(source_id=str(result.source_id), job_id=str(job_id))


@router.post(
    "/{kb_id}/sources/{source_id}/reindex",
    status_code=201,
    response_model=UploadDocOut,
)
async def reindex_source_(
    kb_id: UUID,
    source_id: UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> UploadDocOut:
    qdrant = _qdrant(settings)
    try:
        await purge_source_chunks(
            session, ctx, qdrant,
            kb_id=kb_id, source_id=source_id,
        )
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SourceNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    finally:
        await qdrant.close()

    job_id = uuid4()
    session.add(
        IngestionJobRow(
            id=job_id,
            source_id=source_id,
            tenant_id=ctx.tenant_id,
            status="queued",
            progress=0,
        )
    )
    # Commit explicitly so the background task can read the row via a new session.
    await session.commit()

    factory = get_session_factory(settings)
    runner = JobsRunner(background_tasks)

    async def _kick() -> None:
        await _ingest_in_background(
            factory=factory,
            qdrant_url=settings.qdrant_url,
            qdrant_api_key=settings.qdrant_api_key,
            settings=settings,
            job_id=job_id,
            tenant_id=ctx.tenant_id,
        )

    runner.schedule(_kick)

    return UploadDocOut(source_id=str(source_id), job_id=str(job_id))
