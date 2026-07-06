from dataclasses import dataclass
from uuid import UUID

from tfm_rag.application.integrations.url_safety import (
    normalize_base_url,
    validate_base_url,
)
from tfm_rag.domain.catalog.llm_providers import LLM_PROVIDER_CATALOG
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.ports.repositories import ProviderCredentialRepositoryPort
from tfm_rag.domain.ports.secret_encryptor import SecretEncryptor


@dataclass(frozen=True, slots=True)
class UpsertResult:
    id: UUID
    provider_id: str
    label: str
    max_concurrency: int | None = None
    min_request_interval_seconds: float | None = None


async def upsert_provider_credential(
    *,
    credentials_repo: ProviderCredentialRepositoryPort,
    encryptor: SecretEncryptor,
    provider_id: str,
    label: str,
    api_key: str,
    base_url: str | None = None,
    max_concurrency: int | None = None,
    min_request_interval_seconds: float | None = None,
) -> UpsertResult:
    if max_concurrency is not None and max_concurrency < 1:
        raise ValidationError("max_concurrency must be a positive integer")
    if min_request_interval_seconds is not None and min_request_interval_seconds <= 0:
        raise ValidationError("min_request_interval_seconds must be > 0")
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
    # Canonicalize before persisting so trailing slashes never produce
    # double-slash paths when joined later (e.g. /v1/ + /chat/completions).
    if base_url:
        base_url = normalize_base_url(base_url)
    # SSRF guard at save time: reject private/loopback/metadata base_urls so a
    # malicious endpoint can never be persisted (the test/use paths also guard,
    # but a credential saved without testing would otherwise slip through).
    if base_url:
        validate_base_url(base_url)

    existing = await credentials_repo.find_by_provider_and_label(provider_id, label)

    if existing is not None:
        updated = await credentials_repo.update_credential(
            existing.id,
            api_key_encrypted=encryptor.encrypt(api_key.encode("utf-8")),
            base_url=base_url,
            max_concurrency=max_concurrency,
            min_request_interval_seconds=min_request_interval_seconds,
        )
        return UpsertResult(
            id=updated.id,
            provider_id=updated.provider_id,
            label=updated.label,
            max_concurrency=updated.max_concurrency,
            min_request_interval_seconds=updated.min_request_interval_seconds,
        )

    created = await credentials_repo.create_credential(
        provider_id=provider_id,
        label=label,
        api_key_encrypted=encryptor.encrypt(api_key.encode("utf-8")),
        base_url=base_url,
        max_concurrency=max_concurrency,
        min_request_interval_seconds=min_request_interval_seconds,
    )
    return UpsertResult(
        id=created.id,
        provider_id=created.provider_id,
        label=created.label,
        max_concurrency=created.max_concurrency,
        min_request_interval_seconds=created.min_request_interval_seconds,
    )
