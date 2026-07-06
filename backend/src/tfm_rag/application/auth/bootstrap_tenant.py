from dataclasses import dataclass
from uuid import UUID, uuid4

from tfm_rag.domain.ports.repositories import TenantRepositoryPort


@dataclass(frozen=True, slots=True)
class BootstrapTenantResult:
    tenant_id: UUID
    qdrant_collection_prefix: str
    storage_prefix: str


async def bootstrap_tenant(
    *,
    tenants_repo: TenantRepositoryPort,
    name: str,
) -> BootstrapTenantResult:
    """Create a fresh tenant + its default Ollama provider credential.

    Commit contract: NOTHING is committed here — both port methods flush
    only (see `TenantRepositoryPort`). Bootstrap runs inside the
    register/Google-login request, whose session dependency commits the
    whole user+tenant+credential unit of work atomically at request end.
    The tenant is created (and flushed) before the credential so the
    credential's FK to tenants.id resolves.
    """
    tenant_id = uuid4()
    prefix = f"kb_chunks__{tenant_id}"
    storage = f"tenant_{tenant_id}/"
    await tenants_repo.create_tenant(
        tenant_id=tenant_id,
        name=name,
        qdrant_collection_prefix=prefix,
        storage_prefix=storage,
    )
    await tenants_repo.add_default_ollama_credential(tenant_id=tenant_id)
    return BootstrapTenantResult(
        tenant_id=tenant_id,
        qdrant_collection_prefix=prefix,
        storage_prefix=storage,
    )
