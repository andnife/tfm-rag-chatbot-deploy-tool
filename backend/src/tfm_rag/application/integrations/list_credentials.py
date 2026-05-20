from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.infrastructure.persistence.repositories.credentials_repo import (
    ProviderCredentialRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext


@dataclass(frozen=True, slots=True)
class CredentialView:
    id: UUID
    provider_id: str
    label: str
    base_url: str | None
    config_source: str
    created_at: datetime


async def list_credentials(
    session: AsyncSession,
    ctx: RequestContext,
) -> list[CredentialView]:
    repo = ProviderCredentialRepository(session, ctx)
    rows = await repo.list(limit=200, offset=0)
    return [
        CredentialView(
            id=r.id,
            provider_id=r.provider_id,
            label=r.label,
            base_url=r.base_url,
            config_source=r.config_source,
            created_at=r.created_at,
        )
        for r in rows
    ]
