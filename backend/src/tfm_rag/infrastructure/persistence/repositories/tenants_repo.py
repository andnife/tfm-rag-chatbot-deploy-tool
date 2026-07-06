from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.common import (
    NotFoundError,
    TenantScopeViolationError,
)
from tfm_rag.infrastructure.persistence.models.provider_credentials import (
    ProviderCredentialRow,
)
from tfm_rag.infrastructure.persistence.models.tenants import TenantRow
from tfm_rag.infrastructure.persistence.repository import (
    BaseRepository,
)


class TenantRepository(BaseRepository[TenantRow]):
    """Repository for the tenants table.

    Special-cased because `tenants` has no `tenant_id` column — the row's own
    `id` IS the tenant.
    """
    model = TenantRow

    def _check_tenant(self, row: object) -> None:
        row_id = getattr(row, "id", None)
        if row_id != self._ctx.tenant_id:
            raise TenantScopeViolationError(
                f"TenantRow id {row_id} != context tenant {self._ctx.tenant_id}"
            )

    async def get(self, row_id: UUID) -> TenantRow:
        if row_id != self._ctx.tenant_id:
            raise NotFoundError(f"TenantRow({row_id}) not found in tenant")
        stmt = select(TenantRow).where(TenantRow.id == row_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"TenantRow({row_id}) not found in tenant")
        return row


class TenantProvisioningRepository:
    """Implements `TenantRepositoryPort` — signup-time tenant provisioning.

    Session-only (no RequestContext): a fresh tenant has, by definition, no
    tenant context yet. Both methods flush and never commit — the auth
    request's `get_session` dependency commits the whole
    user+tenant+credential unit of work atomically at request end (see the
    port's docstring).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_tenant(
        self,
        *,
        tenant_id: UUID,
        name: str,
        qdrant_collection_prefix: str,
        storage_prefix: str,
    ) -> None:
        """Flush the tenant row before returning so a subsequently-inserted
        default credential's FK to tenants.id resolves. Without a
        relationship() declaration the UoW topological sort can emit the
        dependent INSERT first when both rows are added before flush.
        """
        self._session.add(
            TenantRow(
                id=tenant_id,
                name=name,
                qdrant_collection_prefix=qdrant_collection_prefix,
                storage_prefix=storage_prefix,
            )
        )
        await self._session.flush()

    async def add_default_ollama_credential(self, *, tenant_id: UUID) -> None:
        """SERVER_ENV credential: no real api_key (a sentinel bytes value
        satisfies NOT NULL); base_url stays NULL — the adapter reads
        `OLLAMA_BASE_URL` from Settings. Flushes, no commit.
        """
        self._session.add(
            ProviderCredentialRow(
                id=uuid4(),
                tenant_id=tenant_id,
                provider_id="ollama",
                label="default",
                api_key_encrypted=b"server-env-sentinel",
                base_url=None,
                config_source="SERVER_ENV",
            )
        )
        await self._session.flush()
