from sqlalchemy import select

from tfm_rag.infrastructure.persistence.models.provider_credentials import (
    ProviderCredentialRow,
)
from tfm_rag.infrastructure.persistence.repository import BaseRepository


class ProviderCredentialRepository(BaseRepository[ProviderCredentialRow]):
    model = ProviderCredentialRow

    async def find_by_provider_id(
        self, provider_id: str
    ) -> list[ProviderCredentialRow]:
        stmt = (
            select(ProviderCredentialRow)
            .where(
                ProviderCredentialRow.tenant_id == self._ctx.tenant_id,
                ProviderCredentialRow.provider_id == provider_id,
            )
        )
        return list((await self._session.execute(stmt)).scalars().all())
