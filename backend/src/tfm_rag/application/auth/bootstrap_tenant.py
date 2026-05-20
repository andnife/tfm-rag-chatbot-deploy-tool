from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.infrastructure.persistence.models.tenants import TenantRow


@dataclass(frozen=True, slots=True)
class BootstrapTenantResult:
    tenant_id: UUID
    qdrant_collection_prefix: str
    storage_prefix: str


async def bootstrap_tenant(
    session: AsyncSession,
    *,
    name: str,
) -> BootstrapTenantResult:
    """Create a fresh Tenant row.

    NOTE: The default Ollama ProviderCredential is created in plan #6 (after
    CAP-INTEG-CREDENTIALS introduces the table).
    """
    tenant_id = uuid4()
    prefix = f"kb_chunks__{tenant_id}"
    storage = f"tenant_{tenant_id}/"
    row = TenantRow(
        id=tenant_id,
        name=name,
        qdrant_collection_prefix=prefix,
        storage_prefix=storage,
    )
    session.add(row)
    await session.flush()
    return BootstrapTenantResult(
        tenant_id=tenant_id,
        qdrant_collection_prefix=prefix,
        storage_prefix=storage,
    )
