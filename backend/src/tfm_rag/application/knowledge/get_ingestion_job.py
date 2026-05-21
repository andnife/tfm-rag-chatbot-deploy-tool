from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import IngestionJobNotFoundError
from tfm_rag.infrastructure.persistence.repositories.ingestion_jobs_repo import (
    IngestionJobRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

RepoFactory = Callable[
    [AsyncSession, RequestContext], IngestionJobRepository
]


def _default_repo(
    session: AsyncSession, ctx: RequestContext
) -> IngestionJobRepository:
    return IngestionJobRepository(session, ctx)


@dataclass(frozen=True, slots=True)
class IngestionJobView:
    id: UUID
    source_id: UUID
    status: str
    progress: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None


async def get_ingestion_job(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    repo_factory: RepoFactory = _default_repo,
    job_id: UUID,
) -> IngestionJobView:
    repo = repo_factory(session, ctx)
    try:
        row = await repo.get(job_id)
    except NotFoundError as exc:
        raise IngestionJobNotFoundError(str(exc)) from exc
    return IngestionJobView(
        id=row.id,
        source_id=row.source_id,
        status=row.status,
        progress=row.progress,
        error=row.error,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )
