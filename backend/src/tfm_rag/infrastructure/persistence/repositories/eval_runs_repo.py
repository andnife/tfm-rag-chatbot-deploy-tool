from sqlalchemy import select

from tfm_rag.infrastructure.persistence.models.eval_runs import EvalRunRow
from tfm_rag.infrastructure.persistence.repository import BaseRepository


class EvalRunRepository(BaseRepository[EvalRunRow]):
    """Tenant-scoped CRUD for eval_runs. `add`/`get`/`list`/`delete` come
    from BaseRepository; `list_recent` adds a newest-first listing.
    """

    model = EvalRunRow

    async def list_recent(self, *, limit: int = 50) -> list[EvalRunRow]:
        stmt = (
            select(EvalRunRow)
            .where(EvalRunRow.tenant_id == self._ctx.tenant_id)
            .order_by(EvalRunRow.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
