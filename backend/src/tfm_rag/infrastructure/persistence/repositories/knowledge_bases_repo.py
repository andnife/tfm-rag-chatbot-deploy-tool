from sqlalchemy import select

from tfm_rag.infrastructure.persistence.models.knowledge_bases import (
    KnowledgeBaseRow,
)
from tfm_rag.infrastructure.persistence.repository import BaseRepository


class KnowledgeBaseRepository(BaseRepository[KnowledgeBaseRow]):
    model = KnowledgeBaseRow

    async def find_by_name(self, name: str) -> KnowledgeBaseRow | None:
        stmt = select(KnowledgeBaseRow).where(
            KnowledgeBaseRow.tenant_id == self._ctx.tenant_id,
            KnowledgeBaseRow.name == name,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()
