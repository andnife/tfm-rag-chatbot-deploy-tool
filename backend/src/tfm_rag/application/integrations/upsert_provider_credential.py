from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.catalog.llm_providers import LLM_PROVIDER_CATALOG
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.ports.secret_encryptor import SecretEncryptor
from tfm_rag.infrastructure.persistence.models.provider_credentials import (
    ProviderCredentialRow,
)
from tfm_rag.infrastructure.persistence.repositories.credentials_repo import (
    ProviderCredentialRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext


@dataclass(frozen=True, slots=True)
class UpsertResult:
    id: UUID
    provider_id: str
    label: str


async def upsert_provider_credential(
    session: AsyncSession,
    ctx: RequestContext,
    encryptor: SecretEncryptor,
    *,
    provider_id: str,
    label: str,
    api_key: str,
    base_url: str | None = None,
) -> UpsertResult:
    descriptor = LLM_PROVIDER_CATALOG.get(provider_id)
    if descriptor is None:
        raise ValidationError(f"Unknown provider_id: {provider_id}")
    if descriptor.config_source != "TENANT_CREDENTIAL":
        raise ValidationError(
            f"Provider {provider_id} is configured via {descriptor.config_source}; "
            "credentials are not stored per-tenant."
        )
    if descriptor.requires_base_url_input and not base_url:
        raise ValidationError(
            f"Provider {provider_id} requires a base_url"
        )

    repo = ProviderCredentialRepository(session, ctx)

    # Check for existing credential with same (provider_id, label).
    stmt = select(ProviderCredentialRow).where(
        ProviderCredentialRow.tenant_id == ctx.tenant_id,
        ProviderCredentialRow.provider_id == provider_id,
        ProviderCredentialRow.label == label,
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()

    if existing is not None:
        existing.api_key_encrypted = encryptor.encrypt(api_key.encode("utf-8"))
        existing.base_url = base_url
        await session.flush()
        return UpsertResult(
            id=existing.id,
            provider_id=existing.provider_id,
            label=existing.label,
        )

    row = ProviderCredentialRow(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        provider_id=provider_id,
        label=label,
        api_key_encrypted=encryptor.encrypt(api_key.encode("utf-8")),
        base_url=base_url,
        config_source="TENANT_CREDENTIAL",
    )
    await repo.add(row)
    return UpsertResult(id=row.id, provider_id=row.provider_id, label=row.label)
