from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.knowledge import SourceNotFoundError
from tfm_rag.infrastructure.persistence.models.sources import SourceRow


class SourceRepository:
    """Sources are scoped through their parent KB (which is tenant-scoped).

    The use case is responsible for loading the KB first (which enforces
    tenant scope); this repo only operates within an already-validated kb_id.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_kb(self, kb_id: UUID) -> list[SourceRow]:
        stmt = select(SourceRow).where(SourceRow.kb_id == kb_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def get(self, kb_id: UUID, source_id: UUID) -> SourceRow:
        stmt = select(SourceRow).where(
            SourceRow.id == source_id,
            SourceRow.kb_id == kb_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise SourceNotFoundError(
                f"Source({source_id}) not found in KB({kb_id})"
            )
        return row

    async def delete(self, kb_id: UUID, source_id: UUID) -> None:
        stmt = delete(SourceRow).where(
            SourceRow.id == source_id,
            SourceRow.kb_id == kb_id,
        )
        result: CursorResult[Any] = await self._session.execute(stmt)  # type: ignore[assignment]
        if result.rowcount == 0:
            raise SourceNotFoundError(
                f"Source({source_id}) not found in KB({kb_id})"
            )
