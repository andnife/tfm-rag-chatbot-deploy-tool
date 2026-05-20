from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.infrastructure.persistence.repositories.credentials_repo import (
    ProviderCredentialRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext


async def delete_credential(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    credential_id: UUID,
) -> None:
    repo = ProviderCredentialRepository(session, ctx)
    await repo.delete(credential_id)
