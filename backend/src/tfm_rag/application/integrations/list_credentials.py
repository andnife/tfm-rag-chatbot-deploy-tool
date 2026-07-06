from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tfm_rag.domain.ports.repositories import ProviderCredentialRepositoryPort


@dataclass(frozen=True, slots=True)
class CredentialView:
    id: UUID
    provider_id: str
    label: str
    base_url: str | None
    config_source: str
    created_at: datetime
    max_concurrency: int | None = None
    min_request_interval_seconds: float | None = None


async def list_credentials(
    *, credentials_repo: ProviderCredentialRepositoryPort
) -> list[CredentialView]:
    credentials = await credentials_repo.list_credentials(limit=200, offset=0)
    return [
        CredentialView(
            id=c.id,
            provider_id=c.provider_id,
            label=c.label,
            base_url=c.base_url,
            config_source=c.config_source,
            created_at=c.created_at,
            max_concurrency=c.max_concurrency,
            min_request_interval_seconds=c.min_request_interval_seconds,
        )
        for c in credentials
    ]
