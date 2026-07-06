"""Read-only cross-tenant admin overview queries (superadmin surface).

These deliberately query WITHOUT a tenant filter — they are the explicit,
opt-in cross-tenant reads (Option A from the design spec). They delegate to
`AdminOverviewReaderPort`, so tenant isolation everywhere else stays intact.

Credentials are exposed as METADATA ONLY — the encrypted `api_key_encrypted`
blob is never read or decrypted here.
"""
from uuid import UUID

from tfm_rag.domain.entities.admin_overview import TenantDetail, TenantOverview
from tfm_rag.domain.ports.admin import AdminOverviewReaderPort


async def list_tenants_with_users(
    *, reader: AdminOverviewReaderPort
) -> list[TenantOverview]:
    """Every tenant with its users. Cross-tenant: no tenant_id filter."""
    return await reader.list_tenants_with_users()


async def tenant_detail(
    *, reader: AdminOverviewReaderPort, tenant_id: UUID
) -> TenantDetail:
    """A tenant's chatbots, KBs, and credential METADATA (never the key)."""
    return await reader.tenant_detail(tenant_id)
