from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import select

from tfm_rag.domain.catalog.llm_providers import ConfigSource
from tfm_rag.domain.entities.provider_credential import ProviderCredential
from tfm_rag.infrastructure.persistence.models.provider_credentials import (
    ProviderCredentialRow,
)
from tfm_rag.infrastructure.persistence.repository import BaseRepository


class ProviderCredentialRepository(BaseRepository[ProviderCredentialRow]):
    model = ProviderCredentialRow

    @staticmethod
    def _to_entity(row: ProviderCredentialRow) -> ProviderCredential:
        return ProviderCredential(
            id=row.id,
            tenant_id=row.tenant_id,
            provider_id=row.provider_id,
            label=row.label,
            api_key_encrypted=row.api_key_encrypted,
            base_url=row.base_url,
            config_source=cast(ConfigSource, row.config_source),
            created_at=row.created_at,
            updated_at=row.updated_at,
            max_concurrency=row.max_concurrency,
            min_request_interval_seconds=row.min_request_interval_seconds,
        )

    async def get_credential(self, credential_id: UUID) -> ProviderCredential:
        """Domain-typed read. Raises NotFoundError if missing in the tenant."""
        return self._to_entity(await self.get(credential_id))

    async def list_credentials(
        self, *, limit: int, offset: int
    ) -> list[ProviderCredential]:
        return [
            self._to_entity(r)
            for r in await self.list(limit=limit, offset=offset)
        ]

    async def find_by_provider_and_label(
        self, provider_id: str, label: str
    ) -> ProviderCredential | None:
        stmt = select(ProviderCredentialRow).where(
            ProviderCredentialRow.tenant_id == self._ctx.tenant_id,
            ProviderCredentialRow.provider_id == provider_id,
            ProviderCredentialRow.label == label,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._to_entity(row) if row is not None else None

    async def create_credential(
        self,
        *,
        provider_id: str,
        label: str,
        api_key_encrypted: bytes,
        base_url: str | None,
        max_concurrency: int | None,
        min_request_interval_seconds: float | None,
    ) -> ProviderCredential:
        row = ProviderCredentialRow(
            id=uuid4(),
            tenant_id=self._ctx.tenant_id,
            provider_id=provider_id,
            label=label,
            api_key_encrypted=api_key_encrypted,
            base_url=base_url,
            config_source="TENANT_CREDENTIAL",
            max_concurrency=max_concurrency,
            min_request_interval_seconds=min_request_interval_seconds,
        )
        await self.add(row)
        await self._session.commit()
        return self._to_entity(row)

    async def update_credential(
        self,
        credential_id: UUID,
        *,
        api_key_encrypted: bytes,
        base_url: str | None,
        max_concurrency: int | None,
        min_request_interval_seconds: float | None,
    ) -> ProviderCredential:
        row = await self.get(credential_id)
        row.api_key_encrypted = api_key_encrypted
        row.base_url = base_url
        row.max_concurrency = max_concurrency
        row.min_request_interval_seconds = min_request_interval_seconds
        await self._session.flush()
        await self._session.commit()
        return self._to_entity(row)

    async def delete_credential(self, credential_id: UUID) -> None:
        await self.delete(credential_id)
        await self._session.commit()
