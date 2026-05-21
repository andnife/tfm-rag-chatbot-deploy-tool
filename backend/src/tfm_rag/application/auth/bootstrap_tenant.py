from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.infrastructure.persistence.models.provider_credentials import (
    ProviderCredentialRow,
)
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
    """Create a fresh Tenant row + a default Ollama ProviderCredential row.

    The Ollama credential has `config_source=SERVER_ENV` so it doesn't store
    an API key (Ollama doesn't require one); the field carries a sentinel
    encrypted value. The `base_url` is left NULL — the adapter reads
    `OLLAMA_BASE_URL` from Settings.
    """
    tenant_id = uuid4()
    prefix = f"kb_chunks__{tenant_id}"
    storage = f"tenant_{tenant_id}/"
    tenant = TenantRow(
        id=tenant_id,
        name=name,
        qdrant_collection_prefix=prefix,
        storage_prefix=storage,
    )
    session.add(tenant)
    # Flush tenant first so the credential's FK to tenants.id resolves.
    # Without a relationship() declaration the UoW topological sort can
    # emit the dependent INSERT first when both rows are added before flush.
    await session.flush()

    ollama_default = ProviderCredentialRow(
        id=uuid4(),
        tenant_id=tenant_id,
        provider_id="ollama",
        label="default",
        # SERVER_ENV: no real api_key. We store a sentinel bytes value to satisfy NOT NULL.
        api_key_encrypted=b"server-env-sentinel",
        base_url=None,
        config_source="SERVER_ENV",
    )
    session.add(ollama_default)

    await session.flush()
    return BootstrapTenantResult(
        tenant_id=tenant_id,
        qdrant_collection_prefix=prefix,
        storage_prefix=storage,
    )
