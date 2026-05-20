from uuid import UUID, uuid4

import pytest

from tfm_rag.domain.errors.common import NotFoundError, TenantScopeViolation
from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.persistence.models.tenants import TenantRow
from tfm_rag.infrastructure.persistence.repository import (
    BaseRepository,
    RequestContext,
)
from tfm_rag.infrastructure.settings import Settings


class TenantRepository(BaseRepository[TenantRow]):
    """Special-cased repository for the tenants table.

    Unlike most tables, `tenants` has no `tenant_id` column — the row's own
    `id` IS the tenant. We override `_check_tenant` so that a TenantRow being
    added/operated-on is checked against its own `id` instead.
    """
    model = TenantRow

    def _check_tenant(self, row: object) -> None:  # type: ignore[override]
        row_id = getattr(row, "id", None)
        if row_id != self._ctx.tenant_id:
            raise TenantScopeViolation(
                f"TenantRow id {row_id} != context tenant {self._ctx.tenant_id}"
            )

    async def get(self, row_id: UUID) -> TenantRow:  # type: ignore[override]
        # Override base get: filter by id (which is the tenant_id semantically)
        from sqlalchemy import select
        if row_id != self._ctx.tenant_id:
            raise NotFoundError(f"TenantRow({row_id}) not found in tenant")
        stmt = select(TenantRow).where(TenantRow.id == row_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"TenantRow({row_id}) not found in tenant")
        return row


def _tenant(tenant_id: UUID) -> TenantRow:
    return TenantRow(
        id=tenant_id,
        name=f"t-{tenant_id}",
        qdrant_collection_prefix=f"kb_chunks__{tenant_id}",
        storage_prefix=f"tenant_{tenant_id}/",
    )


@pytest.mark.integration
async def test_tenant_a_cannot_see_tenant_b(settings: Settings) -> None:
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)

    tenant_a_id = uuid4()
    tenant_b_id = uuid4()
    ctx_a = RequestContext(tenant_id=tenant_a_id)
    ctx_b = RequestContext(tenant_id=tenant_b_id)

    # Tenant A creates its tenant row
    async with factory() as session:
        repo_a = TenantRepository(session, ctx_a)
        await repo_a.add(_tenant(tenant_a_id))
        await session.commit()

    # Tenant B creates its own
    async with factory() as session:
        repo_b = TenantRepository(session, ctx_b)
        await repo_b.add(_tenant(tenant_b_id))
        await session.commit()

    # Tenant B tries to read tenant A's row by id → NotFound
    async with factory() as session:
        repo_b_read = TenantRepository(session, ctx_b)
        with pytest.raises(NotFoundError):
            await repo_b_read.get(tenant_a_id)

    # Tenant B tries to add a row with tenant_id of A → TenantScopeViolation
    async with factory() as session:
        repo_b_add = TenantRepository(session, ctx_b)
        bad_row = _tenant(tenant_a_id)
        with pytest.raises(TenantScopeViolation):
            await repo_b_add.add(bad_row)

    await engine.dispose()
