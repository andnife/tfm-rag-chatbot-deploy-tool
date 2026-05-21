from sqlalchemy import select

from tfm_rag.infrastructure.persistence.models.ingestion_jobs import (
    IngestionJobRow,
)
from tfm_rag.infrastructure.persistence.repository import BaseRepository


class IngestionJobRepository(BaseRepository[IngestionJobRow]):
    model = IngestionJobRow

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
