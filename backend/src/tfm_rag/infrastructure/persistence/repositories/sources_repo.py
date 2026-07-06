from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.entities.source import IngestStatus, Source, SourceType
from tfm_rag.domain.errors.knowledge import SourceNotFoundError
from tfm_rag.infrastructure.persistence.models.sources import SourceRow


class SourceRepository:
    """Sources are scoped through their parent KB (which is tenant-scoped).

    The use case is responsible for loading the KB first (which enforces
    tenant scope); this repo only operates within an already-validated kb_id.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_entity(row: SourceRow) -> Source:
        return Source(
            id=row.id,
            kb_id=row.kb_id,
            type=cast(SourceType, row.type),
            payload=dict(row.payload or {}),
            ingest_status=cast(IngestStatus, row.ingest_status),
            last_ingest_at=row.last_ingest_at,
            error=row.error,
            description=row.description,
        )

    async def list_sources_by_kb(self, kb_id: UUID) -> list[Source]:
        """Domain-typed read of every source attached to `kb_id`."""
        return [self._to_entity(r) for r in await self.list_by_kb(kb_id)]

    async def get_source(self, kb_id: UUID, source_id: UUID) -> Source:
        """Domain-typed KB-scoped read; raises `SourceNotFoundError`."""
        return self._to_entity(await self.get(kb_id, source_id))

    async def insert_document_source(
        self,
        *,
        source_id: UUID,
        kb_id: UUID,
        storage_uri: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
    ) -> None:
        """Persist a new uploaded-document source (ingest_status='not_started').

        Flushes but does not commit; the router commits it together with the
        queued job it schedules.
        """
        self._session.add(
            SourceRow(
                id=source_id,
                kb_id=kb_id,
                type="document",
                payload={
                    "kind": "upload",
                    "storage_uri": storage_uri,
                    "filename": filename,
                    "mime_type": mime_type,
                    "size_bytes": size_bytes,
                },
                ingest_status="not_started",
            )
        )
        await self._session.flush()

    async def insert_database_source(
        self, *, kb_id: UUID, payload: dict[str, Any]
    ) -> UUID:
        """Persist a new database source (ingest_status='done') and commit.

        Replaces the former inline ``InlineSourcesRepo`` adapter; commits so
        the row is durable at the same point the old use case committed.
        """
        source_id = uuid4()
        self._session.add(
            SourceRow(
                id=source_id,
                kb_id=kb_id,
                type="database",
                payload=payload,
                ingest_status="done",
                last_ingest_at=datetime.now(UTC),
            )
        )
        await self._session.commit()
        return source_id

    async def delete_source(self, kb_id: UUID, source_id: UUID) -> None:
        """KB-scoped delete + commit (raises `SourceNotFoundError` if absent)."""
        await self.delete(kb_id, source_id)
        await self._session.commit()

    async def get_source_unscoped(self, source_id: UUID) -> Source:
        """Domain-typed unscoped read. See `get_by_id_unscoped` for the
        ownership caveat; raises `SourceNotFoundError` if missing.
        """
        return self._to_entity(await self.get_by_id_unscoped(source_id))

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

    async def get_by_id_unscoped(self, source_id: UUID) -> SourceRow:
        """Tenant-agnostic lookup by source_id only.

        UNSCOPED: this does NOT check tenant/KB ownership. Callers MUST
        enforce ownership themselves via the parent KB's tenant scope
        (e.g. checking `row.kb_id` against an allow-list derived from
        the current tenant's chatbots/KBs) before trusting the result.
        Used by `query_database`, which already validates `kb_id` against
        the chatbot's allowed KBs after calling this.
        """
        stmt = select(SourceRow).where(SourceRow.id == source_id)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise SourceNotFoundError(f"Source({source_id}) not found")
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
