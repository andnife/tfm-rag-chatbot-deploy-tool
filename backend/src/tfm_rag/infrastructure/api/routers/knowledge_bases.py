from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

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
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.settings import Settings, get_settings
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore

router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge"])


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
