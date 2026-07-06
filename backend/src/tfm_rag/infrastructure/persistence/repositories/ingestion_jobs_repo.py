from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tfm_rag.domain.entities.ingestion_job import IngestionJob, IngestionStatus
from tfm_rag.domain.entities.knowledge_base import KnowledgeBase
from tfm_rag.domain.entities.source import Source
from tfm_rag.infrastructure.persistence.models.ingestion_jobs import (
    IngestionJobRow,
)
from tfm_rag.infrastructure.persistence.models.knowledge_bases import (
    KnowledgeBaseRow,
)
from tfm_rag.infrastructure.persistence.models.sources import SourceRow
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repositories.sources_repo import (
    SourceRepository,
)
from tfm_rag.infrastructure.persistence.repository import BaseRepository

# Ingestion errors are capped to fit the ingestion_jobs.error / sources.error
# String(2000) columns with headroom (matches the pre-extraction router).
_ERROR_MAXLEN = 1900


def _job_to_entity(row: IngestionJobRow) -> IngestionJob:
    return IngestionJob(
        id=row.id,
        source_id=row.source_id,
        tenant_id=row.tenant_id,
        status=cast(IngestionStatus, row.status),
        progress=row.progress,
        stage=row.stage,
        items_done=row.items_done,
        items_total=row.items_total,
        error=row.error,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


class IngestionJobRepository(BaseRepository[IngestionJobRow]):
    model = IngestionJobRow

    @staticmethod
    def _to_entity(row: IngestionJobRow) -> IngestionJob:
        return _job_to_entity(row)

    async def get_ingestion_job(self, job_id: UUID) -> IngestionJob:
        """Domain-typed read. Raises NotFoundError if missing in the tenant."""
        return self._to_entity(await self.get(job_id))

    async def create_queued_job(self, *, source_id: UUID) -> UUID:
        """Persist a queued job for `source_id`; flush only (no commit)."""
        job_id = uuid4()
        self._session.add(
            IngestionJobRow(
                id=job_id,
                source_id=source_id,
                tenant_id=self._ctx.tenant_id,
                status="queued",
                progress=0,
            )
        )
        await self._session.flush()
        return job_id

    async def list_for_source(self, source_id: str) -> list[IngestionJobRow]:
        stmt = (
            select(IngestionJobRow)
            .where(
                IngestionJobRow.tenant_id == self._ctx.tenant_id,
                IngestionJobRow.source_id == source_id,
            )
            .order_by(IngestionJobRow.started_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())


class IngestionJobStore:
    """Background state machine adapter (`IngestionJobStorePort`).

    Opens a fresh session per mutation and commits it, so a concurrent status
    poller sees each running/progress/done/failed transition independently —
    exactly the behaviour of the pre-extraction ``_ingest_in_background``.
    """

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        tenant_id: UUID,
    ) -> None:
        self._factory = factory
        self._tenant_id = tenant_id

    async def load_job(self, job_id: UUID) -> IngestionJob | None:
        async with self._factory() as s:
            row = (
                await s.execute(
                    select(IngestionJobRow).where(
                        IngestionJobRow.id == job_id,
                        IngestionJobRow.tenant_id == self._tenant_id,
                    )
                )
            ).scalar_one_or_none()
            return _job_to_entity(row) if row is not None else None

    async def load_source(self, source_id: UUID) -> Source | None:
        async with self._factory() as s:
            row = (
                await s.execute(
                    select(SourceRow).where(SourceRow.id == source_id)
                )
            ).scalar_one_or_none()
            return SourceRepository._to_entity(row) if row is not None else None

    async def load_knowledge_base(self, kb_id: UUID) -> KnowledgeBase | None:
        async with self._factory() as s:
            row = (
                await s.execute(
                    select(KnowledgeBaseRow).where(
                        KnowledgeBaseRow.id == kb_id,
                        KnowledgeBaseRow.tenant_id == self._tenant_id,
                    )
                )
            ).scalar_one_or_none()
            return (
                KnowledgeBaseRepository._to_entity(row)
                if row is not None
                else None
            )

    async def mark_running(self, *, job_id: UUID, source_id: UUID) -> None:
        async with self._factory() as s:
            await s.execute(
                update(IngestionJobRow)
                .where(IngestionJobRow.id == job_id)
                .values(status="running", progress=0)
            )
            await s.execute(
                update(SourceRow)
                .where(SourceRow.id == source_id)
                .values(ingest_status="running")
            )
            await s.commit()

    async def update_progress(
        self,
        *,
        job_id: UUID,
        progress: int,
        stage: str | None,
        items_done: int | None,
        items_total: int | None,
    ) -> None:
        async with self._factory() as s:
            await s.execute(
                update(IngestionJobRow)
                .where(IngestionJobRow.id == job_id)
                .values(
                    progress=progress,
                    stage=stage,
                    items_done=items_done,
                    items_total=items_total,
                )
            )
            await s.commit()

    async def mark_done(self, *, job_id: UUID, source_id: UUID) -> None:
        async with self._factory() as s:
            now = datetime.now(UTC)
            await s.execute(
                update(IngestionJobRow)
                .where(IngestionJobRow.id == job_id)
                .values(
                    status="done",
                    progress=100,
                    stage=None,
                    items_done=None,
                    items_total=None,
                    finished_at=now,
                )
            )
            await s.execute(
                update(SourceRow)
                .where(SourceRow.id == source_id)
                .values(ingest_status="done", last_ingest_at=now, error=None)
            )
            await s.commit()

    async def fail_job(self, *, job_id: UUID, error: str) -> None:
        async with self._factory() as s:
            await s.execute(
                update(IngestionJobRow)
                .where(IngestionJobRow.id == job_id)
                .values(
                    status="failed",
                    error=error[:_ERROR_MAXLEN],
                    finished_at=datetime.now(UTC),
                )
            )
            await s.commit()

    async def fail_job_and_source(
        self, *, job_id: UUID, source_id: UUID, error: str
    ) -> None:
        async with self._factory() as s:
            await s.execute(
                update(IngestionJobRow)
                .where(IngestionJobRow.id == job_id)
                .values(
                    status="failed",
                    error=error[:_ERROR_MAXLEN],
                    finished_at=datetime.now(UTC),
                )
            )
            await s.execute(
                update(SourceRow)
                .where(SourceRow.id == source_id)
                .values(ingest_status="failed", error=error[:_ERROR_MAXLEN])
            )
            await s.commit()

    async def set_source_description(
        self, *, source_id: UUID, description: str
    ) -> None:
        async with self._factory() as s:
            await s.execute(
                update(SourceRow)
                .where(SourceRow.id == source_id)
                .values(description=description)
            )
            await s.commit()
