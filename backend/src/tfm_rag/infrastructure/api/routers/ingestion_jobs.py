from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.knowledge.get_ingestion_job import get_ingestion_job
from tfm_rag.domain.errors.knowledge import IngestionJobNotFoundError
from tfm_rag.infrastructure.api.dependencies import (
    get_current_context,
    get_session,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

router = APIRouter(prefix="/api/ingestion-jobs", tags=["ingestion"])


class IngestionJobOut(BaseModel):
    id: str
    source_id: str
    status: str
    progress: int
    error: str | None
    started_at: str
    finished_at: str | None


@router.get("/{job_id}", response_model=IngestionJobOut)
async def get_(
    job_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> IngestionJobOut:
    try:
        view = await get_ingestion_job(session, ctx, job_id=job_id)
    except IngestionJobNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return IngestionJobOut(
        id=str(view.id),
        source_id=str(view.source_id),
        status=view.status,
        progress=view.progress,
        error=view.error,
        started_at=view.started_at.isoformat(),
        finished_at=view.finished_at.isoformat() if view.finished_at else None,
    )
