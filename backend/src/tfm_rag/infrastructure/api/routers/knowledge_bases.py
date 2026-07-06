from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.chat.retrieve_docs import retrieve_docs
from tfm_rag.application.integrations.endpoint_resolver import resolve_inference_target
from tfm_rag.application.knowledge.attach_database_source import (
    AttachDatabaseResult,
    attach_database_source,
)
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
from tfm_rag.application.knowledge.list_knowledge_bases import (
    list_knowledge_bases,
)
from tfm_rag.application.knowledge.list_sources import list_sources
from tfm_rag.application.knowledge.reindex_source import purge_source_chunks
from tfm_rag.application.knowledge.run_ingestion_job import run_ingestion_job
from tfm_rag.application.knowledge.test_source_connection import (
    test_source_connection,
)
from tfm_rag.application.knowledge.update_knowledge_base import (
    _UNSET,
    update_knowledge_base,
)
from tfm_rag.domain.entities.source import SourceType
from tfm_rag.domain.errors.chat import UnsupportedProviderError
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.errors.knowledge import (
    DatabaseConnectionError,
    IncompatibleEmbeddingsError,
    KnowledgeBaseInUseError,
    KnowledgeBaseNotFoundError,
    SchemaIntrospectionError,
    SourceNotFoundError,
    UnsupportedDatabaseDialectError,
)
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.database_source_spec import (
    DatabaseSourceSpec,
)
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.model_ref import ModelRef
from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk
from tfm_rag.infrastructure.api.dependencies import (
    get_current_context,
    get_session,
    get_session_factory,  # noqa: PLC2701
)
from tfm_rag.infrastructure.chunkers.factory import select_chunker
from tfm_rag.infrastructure.database_connectors.source_tester import (
    DATABASE_CONNECTORS,
)
from tfm_rag.infrastructure.document_loaders.csv import CsvLoader
from tfm_rag.infrastructure.document_loaders.dispatcher import LoaderDispatcher
from tfm_rag.infrastructure.document_loaders.docx import DocxLoader
from tfm_rag.infrastructure.document_loaders.markdown import MarkdownLoader
from tfm_rag.infrastructure.document_loaders.pdf import PdfLoader
from tfm_rag.infrastructure.document_loaders.txt import TxtLoader
from tfm_rag.infrastructure.embedders.dispatcher import EmbedderDispatcher
from tfm_rag.infrastructure.jobs.runner import JobsRunner
from tfm_rag.infrastructure.llm_providers.dispatcher import LLMDispatcher
from tfm_rag.infrastructure.persistence.repositories.credentials_repo import (
    ProviderCredentialRepository,
)
from tfm_rag.infrastructure.persistence.repositories.ingestion_jobs_repo import (
    IngestionJobRepository,
    IngestionJobStore,
)
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repositories.sources_repo import (
    SourceRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.secrets.fernet_encryptor import (
    FernetSecretEncryptor,
)
from tfm_rag.infrastructure.settings import Settings, get_settings
from tfm_rag.infrastructure.storage.local import LocalStorage
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore

router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge"])

_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

# Derive the mime type from the filename extension rather than trusting the
# browser's content_type, which is unreliable for several supported formats
# (e.g. browsers send an empty type for `.md`, so it would be rejected). Keep
# in sync with SUPPORTED_MIME_TYPES in attach_document_source.
_EXT_TO_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".docx": (
        "application/vnd.openxmlformats-officedocument."
        "wordprocessingml.document"
    ),
}


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
    credential_id: UUID
    model_id: str
    dim: int = Field(..., ge=8, le=4096)
    # provider_id accepted for backward-compat with old clients but ignored.
    provider_id: str | None = None

    def to_vo(self) -> EmbeddingSelection:
        return EmbeddingSelection(
            credential_id=self.credential_id,
            model_id=self.model_id,
            dim=self.dim,
        )


class ModelRefIn(BaseModel):
    credential_id: UUID
    model_id: str

    def to_vo(self) -> ModelRef:
        return ModelRef(credential_id=self.credential_id, model_id=self.model_id)


class CreateKbIn(BaseModel):
    name: str
    description: str | None = None
    chunking_config: ChunkingConfigIn = Field(default_factory=ChunkingConfigIn)
    embedding_selection: EmbeddingSelectionIn
    description_llm: ModelRefIn | None = None


class UpdateKbIn(BaseModel):
    name: str | None = None
    description: str | None = None
    chunking_config: ChunkingConfigIn | None = None
    embedding_selection: EmbeddingSelectionIn | None = None
    # Tri-state on the wire: field absent from the JSON body -> "no change"
    # (patch_ checks `"description_llm" in body.model_fields_set` and passes
    # the use-case's _UNSET sentinel); field present with `null` -> "clear
    # the selection"; field present with an object -> "set".
    description_llm: ModelRefIn | None = None


class KbOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: str | None
    chunking_config: dict[str, Any]
    embedding_selection: dict[str, Any]
    description_llm: dict[str, Any] | None

    @classmethod
    def from_view(cls, v: KnowledgeBaseView) -> "KbOut":
        return cls(
            id=str(v.id),
            tenant_id=str(v.tenant_id),
            name=v.name,
            description=v.description,
            chunking_config=v.chunking_config.to_dict(),
            embedding_selection=v.embedding_selection.to_dict(),
            description_llm=(
                v.description_llm.to_dict() if v.description_llm is not None else None
            ),
        )


class SourceOut(BaseModel):
    id: str
    kb_id: str
    type: SourceType
    ingest_status: str
    filename: str | None = None
    error: str | None = None
    description: str | None = None
    last_ingest_at: str | None = None  # ISO-8601, last successful indexing


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


def _storage(settings: Settings) -> LocalStorage:
    return LocalStorage(root=settings.storage_local_path)


def _loader_dispatcher() -> LoaderDispatcher:
    return LoaderDispatcher([
        PdfLoader(),
        TxtLoader(),
        DocxLoader(),
        CsvLoader(),
        MarkdownLoader(),
    ])


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
            kb_repo=KnowledgeBaseRepository(session, ctx),
            qdrant=qdrant,
            tenant_id=ctx.tenant_id,
            name=body.name,
            description=body.description,
            chunking_config=body.chunking_config.to_vo(),
            embedding_selection=body.embedding_selection.to_vo(),
            description_llm=(
                body.description_llm.to_vo() if body.description_llm else None
            ),
        )
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        await qdrant.close()
    return KbOut.from_view(view)


@router.get("", response_model=list[KbOut])
async def list_(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100_000),
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> list[KbOut]:
    views = await list_knowledge_bases(
        kb_repo=KnowledgeBaseRepository(session, ctx), limit=limit, offset=offset
    )
    return [KbOut.from_view(v) for v in views]


@router.get("/{kb_id}", response_model=KbDetailOut)
async def get_(
    kb_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> KbDetailOut:
    try:
        detail = await get_knowledge_base(
            kb_repo=KnowledgeBaseRepository(session, ctx),
            sources_repo=SourceRepository(session),
            kb_id=kb_id,
        )
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
                filename=s.filename,
                error=s.error,
                description=s.description,
                last_ingest_at=s.last_ingest_at.isoformat() if s.last_ingest_at else None,
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
            kb_repo=KnowledgeBaseRepository(session, ctx),
            qdrant=qdrant,
            tenant_id=ctx.tenant_id,
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
            description_llm=(
                (body.description_llm.to_vo() if body.description_llm else None)
                if "description_llm" in body.model_fields_set
                else _UNSET
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
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> None:
    qdrant = _qdrant(settings)
    try:
        await delete_knowledge_base(
            kb_repo=KnowledgeBaseRepository(session, ctx),
            sources_repo=SourceRepository(session),
            tenant_id=ctx.tenant_id,
            qdrant=qdrant,
            storage=_storage(settings),
            kb_id=kb_id,
        )
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except KnowledgeBaseInUseError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    finally:
        await qdrant.close()


@router.get("/{kb_id}/sources", response_model=list[SourceOut])
async def list_sources_(
    kb_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> list[SourceOut]:
    try:
        views = await list_sources(
            kb_repo=KnowledgeBaseRepository(session, ctx),
            sources_repo=SourceRepository(session),
            kb_id=kb_id,
        )
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [
        SourceOut(
            id=str(s.id),
            kb_id=str(s.kb_id),
            type=s.type,
            ingest_status=s.ingest_status,
            filename=s.filename,
            error=s.error,
            description=s.description,
            last_ingest_at=s.last_ingest_at.isoformat() if s.last_ingest_at else None,
        )
        for s in views
    ]


@router.delete("/{kb_id}/sources/{source_id}", status_code=204)
async def detach_source_(
    kb_id: UUID,
    source_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> None:
    qdrant = _qdrant(settings)
    try:
        await detach_source(
            kb_repo=KnowledgeBaseRepository(session, ctx),
            sources_repo=SourceRepository(session),
            tenant_id=ctx.tenant_id,
            qdrant=qdrant,
            storage=_storage(settings),
            kb_id=kb_id,
            source_id=source_id,
        )
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SourceNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    finally:
        await qdrant.close()


@router.post("/{kb_id}/sources/test-connection")
async def test_connection_(
    kb_id: UUID,
    body: TestConnectionIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> dict[str, Any]:
    # Validate that the KB exists and belongs to the tenant before testing.
    try:
        await get_knowledge_base(
            kb_repo=KnowledgeBaseRepository(session, ctx),
            sources_repo=SourceRepository(session),
            kb_id=kb_id,
        )
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    result = await test_source_connection(spec_type=body.type, spec=body.spec)
    return {"ok": result.ok, "error": result.error, "details": result.details}


def _schedule_ingestion(
    *,
    background_tasks: BackgroundTasks,
    settings: Settings,
    tenant_id: UUID,
    job_id: UUID,
) -> None:
    """Compose the ingestion runner's ports and schedule it in the background.

    The runner opens its own Qdrant client + per-transition sessions (via the
    `IngestionJobStore`), so the request session is free to close.
    """
    factory = get_session_factory(settings)
    encryptor = FernetSecretEncryptor(settings.fernet_key)

    async def _resolve_endpoint(
        credential_id: UUID,
    ) -> tuple[str, str, str | None]:
        async with factory() as s:
            return await resolve_inference_target(
                credential_id=credential_id,
                credentials_repo=ProviderCredentialRepository(
                    s, RequestContext(tenant_id=tenant_id)
                ),
                encryptor=encryptor,
                ollama_base_url=settings.ollama_base_url,
            )

    async def _kick() -> None:
        qdrant = QdrantStore(
            url=settings.qdrant_url, api_key=settings.qdrant_api_key
        )
        try:
            await run_ingestion_job(
                job_id=job_id,
                tenant_id=tenant_id,
                jobs=IngestionJobStore(factory, tenant_id),
                resolve_endpoint=_resolve_endpoint,
                storage=_storage(settings),
                loader_dispatcher=_loader_dispatcher(),
                make_chunker=select_chunker,
                embedders=EmbedderDispatcher.default(),
                llms=LLMDispatcher.default(),
                qdrant=qdrant,
            )
        finally:
            await qdrant.close()

    JobsRunner(background_tasks).schedule(_kick)


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
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    mime = _EXT_TO_MIME.get(ext) or file.content_type or "application/octet-stream"
    try:
        result = await attach_document_source(
            kb_repo=KnowledgeBaseRepository(session, ctx),
            sources_repo=SourceRepository(session),
            storage=_storage(settings),
            tenant_id=ctx.tenant_id,
            kb_id=kb_id,
            filename=name,
            mime_type=mime,
            content=content,
        )
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Persist the queued job in the same session, then commit explicitly so the
    # background runner can read source+job via its own sessions.
    job_id = await IngestionJobRepository(session, ctx).create_queued_job(
        source_id=result.source_id
    )
    await session.commit()

    _schedule_ingestion(
        background_tasks=background_tasks,
        settings=settings,
        tenant_id=ctx.tenant_id,
        job_id=job_id,
    )

    return UploadDocOut(source_id=str(result.source_id), job_id=str(job_id))


class AttachDatabaseIn(BaseModel):
    driver: Literal["postgres", "mysql"]
    host: str
    port: int = Field(..., ge=1, le=65535)
    db_name: str
    username: str
    password: str
    ssl_mode: Literal["disable", "require"] = "disable"


class AttachDatabaseOut(BaseModel):
    source_id: str
    snapshot_tables: int
    snapshot_captured_at: datetime


@router.post(
    "/{kb_id}/sources/databases",
    status_code=201,
    response_model=AttachDatabaseOut,
)
async def attach_database_source_(
    kb_id: UUID,
    body: AttachDatabaseIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AttachDatabaseOut:
    spec = DatabaseSourceSpec(
        driver=body.driver,
        host=body.host,
        port=body.port,
        db_name=body.db_name,
        username=body.username,
        password=body.password,
        ssl_mode=body.ssl_mode,
    )
    try:
        result: AttachDatabaseResult = await attach_database_source(
            kb_repo=KnowledgeBaseRepository(session, ctx),
            sources_repo=SourceRepository(session),
            kb_id=kb_id,
            spec=spec,
            encryptor=FernetSecretEncryptor(settings.fernet_key),
            connectors=DATABASE_CONNECTORS,
        )
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UnsupportedDatabaseDialectError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (DatabaseConnectionError, SchemaIntrospectionError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return AttachDatabaseOut(
        source_id=str(result.source_id),
        snapshot_tables=result.snapshot_table_count,
        snapshot_captured_at=result.snapshot_captured_at,
    )


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
            kb_repo=KnowledgeBaseRepository(session, ctx),
            sources_repo=SourceRepository(session),
            qdrant=qdrant,
            tenant_id=ctx.tenant_id,
            kb_id=kb_id,
            source_id=source_id,
        )
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SourceNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    finally:
        await qdrant.close()

    job_id = await IngestionJobRepository(session, ctx).create_queued_job(
        source_id=source_id
    )
    await session.commit()

    _schedule_ingestion(
        background_tasks=background_tasks,
        settings=settings,
        tenant_id=ctx.tenant_id,
        job_id=job_id,
    )

    return UploadDocOut(source_id=str(source_id), job_id=str(job_id))


class SearchIn(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=50)
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class SearchHitOut(BaseModel):
    point_id: str
    content: str
    source_id: str
    source_filename: str
    chunk_index: int
    score: float
    metadata: dict[str, Any]

    @classmethod
    def from_chunk(cls, c: RetrievedChunk) -> "SearchHitOut":
        return cls(
            point_id=c.point_id,
            content=c.content,
            source_id=str(c.source_id),
            source_filename=c.source_filename,
            chunk_index=c.chunk_index,
            score=c.score,
            metadata=c.metadata,
        )


@router.post("/{kb_id}/search", response_model=list[SearchHitOut])
async def search_(
    kb_id: UUID,
    body: SearchIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> list[SearchHitOut]:
    qdrant = _qdrant(settings)
    try:
        chunks = await retrieve_docs(
            tenant_id=ctx.tenant_id,
            qdrant=qdrant,
            dispatcher=EmbedderDispatcher.default(),
            kb_repo=KnowledgeBaseRepository(session, ctx),
            credentials_repo=ProviderCredentialRepository(session, ctx),
            encryptor=FernetSecretEncryptor(settings.fernet_key),
            ollama_base_url=settings.ollama_base_url,
            kb_ids=[kb_id],
            query=body.query,
            top_k=body.top_k,
            score_threshold=body.score_threshold,
        )
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except IncompatibleEmbeddingsError as exc:
        # Cannot happen for a single kb_id, but keep the mapping for symmetry.
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except UnsupportedProviderError as exc:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)
        ) from exc
    finally:
        await qdrant.close()
    return [SearchHitOut.from_chunk(c) for c in chunks]
