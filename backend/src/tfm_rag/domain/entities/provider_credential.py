from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tfm_rag.domain.catalog.llm_providers import ConfigSource


@dataclass(frozen=True, slots=True)
class ProviderCredential:
    id: UUID
    tenant_id: UUID
    provider_id: str
    label: str
    api_key_encrypted: bytes
    base_url: str | None
    config_source: ConfigSource
    created_at: datetime
    updated_at: datetime
    # Optional per-credential outbound-call throttling (see
    # ProviderCredentialRow for the rationale); unset by most credentials.
    max_concurrency: int | None = None
    min_request_interval_seconds: float | None = None
