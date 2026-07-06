from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import IngestionJobNotFoundError
from tfm_rag.domain.ports.repositories import IngestionJobRepositoryPort


@dataclass(frozen=True, slots=True)
class IngestionJobView:
    id: UUID
    source_id: UUID
    status: str
    progress: int
    stage: str | None
    items_done: int | None
    items_total: int | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None


async def get_ingestion_job(
    *,
    jobs_repo: IngestionJobRepositoryPort,
    job_id: UUID,
) -> IngestionJobView:
    try:
        job = await jobs_repo.get_ingestion_job(job_id)
    except NotFoundError as exc:
        raise IngestionJobNotFoundError(str(exc)) from exc
    return IngestionJobView(
        id=job.id,
        source_id=job.source_id,
        status=job.status,
        progress=job.progress,
        stage=job.stage,
        items_done=job.items_done,
        items_total=job.items_total,
        error=job.error,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )
