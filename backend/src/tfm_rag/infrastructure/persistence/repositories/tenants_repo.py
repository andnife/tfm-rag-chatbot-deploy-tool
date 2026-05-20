from uuid import UUID

from sqlalchemy import select

from tfm_rag.domain.errors.common import (
    NotFoundError,
    TenantScopeViolationError,
)
from tfm_rag.infrastructure.persistence.models.tenants import TenantRow
from tfm_rag.infrastructure.persistence.repository import (
    BaseRepository,
    RequestContext,
)


class TenantRepository(BaseRepository[TenantRow]):
    """Repository for the tenants table.

    Special-cased because `tenants` has no `tenant_id` column — the row's own
    `id` IS the tenant.
    """
    model = TenantRow

    def _check_tenant(self, row: object) -> None:  # type: ignore[override]
        row_id = getattr(row, "id", None)
        if row_id != self._ctx.tenant_id:
            raise TenantScopeViolationError(
                f"TenantRow id {row_id} != context tenant {self._ctx.tenant_id}"
            )

    async def get(self, row_id: UUID) -> TenantRow:  # type: ignore[override]
        if row_id != self._ctx.tenant_id:
            raise NotFoundError(f"TenantRow({row_id}) not found in tenant")
        stmt = select(TenantRow).where(TenantRow.id == row_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"TenantRow({row_id}) not found in tenant")
        return row
