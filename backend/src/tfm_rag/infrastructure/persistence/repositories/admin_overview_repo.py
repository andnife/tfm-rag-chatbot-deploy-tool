"""Implements `AdminOverviewReaderPort` — cross-tenant, read-only queries for
the superadmin overview surface.

Deliberately does NOT use `BaseRepository`: these are the explicit, opt-in
cross-tenant reads (Option A from the design spec), so tenant isolation
everywhere else stays intact. Credentials are exposed as METADATA ONLY — the
encrypted `api_key_encrypted` blob is never read or decrypted here.
"""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.entities.admin_overview import (
    ChatbotSummary,
    CredentialSummary,
    KnowledgeBaseSummary,
    TenantDetail,
    TenantOverview,
    TenantUserSummary,
)
from tfm_rag.infrastructure.persistence.models.chatbots import ChatbotRow
from tfm_rag.infrastructure.persistence.models.knowledge_bases import (
    KnowledgeBaseRow,
)
from tfm_rag.infrastructure.persistence.models.provider_credentials import (
    ProviderCredentialRow,
)
from tfm_rag.infrastructure.persistence.models.tenants import TenantRow
from tfm_rag.infrastructure.persistence.models.users import UserRow


class AdminOverviewReader:
    """Implements `AdminOverviewReaderPort`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_tenants_with_users(self) -> list[TenantOverview]:
        """Every tenant with its users. Cross-tenant: no tenant_id filter."""
        tenants = (await self._session.execute(select(TenantRow))).scalars().all()
        users = (await self._session.execute(select(UserRow))).scalars().all()
        by_tenant: dict[UUID, list[TenantUserSummary]] = {}
        for u in users:
            by_tenant.setdefault(u.tenant_id, []).append(
                TenantUserSummary(
                    id=u.id,
                    email=u.email,
                    is_superadmin=bool(u.is_superadmin),
                    created_at=u.created_at,
                )
            )
        return [
            TenantOverview(tenant_id=t.id, name=t.name, users=by_tenant.get(t.id, []))
            for t in tenants
        ]

    async def tenant_detail(self, tenant_id: UUID) -> TenantDetail:
        """A tenant's chatbots, KBs, and credential METADATA (never the key)."""
        chatbots = (
            await self._session.execute(
                select(ChatbotRow).where(ChatbotRow.tenant_id == tenant_id)
            )
        ).scalars().all()
        kbs = (
            await self._session.execute(
                select(KnowledgeBaseRow).where(KnowledgeBaseRow.tenant_id == tenant_id)
            )
        ).scalars().all()
        creds = (
            await self._session.execute(
                select(ProviderCredentialRow).where(
                    ProviderCredentialRow.tenant_id == tenant_id
                )
            )
        ).scalars().all()
        return TenantDetail(
            tenant_id=tenant_id,
            chatbots=[
                ChatbotSummary(id=c.id, name=c.name, description=c.description)
                for c in chatbots
            ],
            knowledge_bases=[
                KnowledgeBaseSummary(id=k.id, name=k.name, description=k.description)
                for k in kbs
            ],
            credentials=[
                CredentialSummary(
                    id=c.id,
                    provider_id=c.provider_id,
                    label=c.label,
                    base_url=c.base_url,
                    config_source=c.config_source,
                )
                for c in creds
            ],
        )
