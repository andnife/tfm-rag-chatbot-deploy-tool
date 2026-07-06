"""Admin overview port — the cross-tenant, read-only superadmin surface.

Kept separate from `domain/ports/repositories.py` because it is not a
per-aggregate repository contract: it is a purpose-built reporting query
that deliberately reads WITHOUT a tenant filter (Option A from the design
spec). See `application/admin/overview.py` for the security rationale.
"""
from typing import Protocol
from uuid import UUID

from tfm_rag.domain.entities.admin_overview import TenantDetail, TenantOverview


class AdminOverviewReaderPort(Protocol):
    """Cross-tenant, read-only admin overview queries (superadmin surface)."""

    async def list_tenants_with_users(self) -> list[TenantOverview]:
        """Every tenant with its users. Cross-tenant: no tenant_id filter."""
        ...

    async def tenant_detail(self, tenant_id: UUID) -> TenantDetail:
        """A tenant's chatbots, KBs, and credential METADATA (never the key)."""
        ...
