from typing import Protocol
from uuid import UUID

from tfm_rag.application.integrations.url_safety import validate_base_url
from tfm_rag.domain.catalog.embedding_providers import EMBEDDING_PROVIDER_CATALOG
from tfm_rag.domain.catalog.llm_providers import LLM_PROVIDER_CATALOG, ConfigSource
from tfm_rag.domain.errors.chat import UnsupportedProviderError
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.ports.secret_encryptor import SecretEncryptor

_OPENAI_PUBLIC_BASE_URL = "https://api.openai.com/v1"


class _CredentialRow(Protocol):
    # Read-only members → covariant, so the `ProviderCredential` entity
    # returned by `ProviderCredentialRepositoryPort.get_credential` satisfies
    # this narrow structural view.
    @property
    def provider_id(self) -> str: ...
    @property
    def api_key_encrypted(self) -> bytes: ...
    @property
    def base_url(self) -> str | None: ...


class _CredentialsRepo(Protocol):
    # Narrow structural port: the `ProviderCredentialRepositoryPort` domain
    # port (whose `get_credential` returns a `ProviderCredential` entity) is
    # assignable here — the entity carries the three fields we read below.
    async def get_credential(self, credential_id: UUID) -> _CredentialRow: ...


def _config_source(provider_id: str) -> ConfigSource:
    descriptor = LLM_PROVIDER_CATALOG.get(provider_id) or EMBEDDING_PROVIDER_CATALOG.get(
        provider_id
    )
    if descriptor is None:
        raise UnsupportedProviderError(f"Unknown provider_id={provider_id!r}")
    return descriptor.config_source


def _resolve_url_and_key(
    provider_id: str,
    row: _CredentialRow,
    encryptor: SecretEncryptor,
    ollama_base_url: str,
) -> tuple[str, str | None]:
    """Shared resolution logic: given a provider_id and credential row, return
    ``(base_url, api_key)``.

    SERVER_ENV (Ollama) → ``(ollama_base_url, None)``; no key decryption.
    TENANT_CREDENTIAL → decrypt key, pick/force base_url, run SSRF check.
    """
    if _config_source(provider_id) == "SERVER_ENV":
        return ollama_base_url, None

    api_key = encryptor.decrypt(row.api_key_encrypted).decode("utf-8")
    if provider_id == "openai":
        base_url = _OPENAI_PUBLIC_BASE_URL
    elif provider_id == "openai_compat":
        if not row.base_url:
            raise ValidationError(
                "openai_compat credential requires a base_url; "
                "set the endpoint URL in the credential configuration."
            )
        base_url = row.base_url
    else:
        base_url = row.base_url or _OPENAI_PUBLIC_BASE_URL
    validate_base_url(base_url)
    return base_url, api_key


async def resolve_inference_target(
    *,
    credential_id: UUID,
    credentials_repo: _CredentialsRepo,
    encryptor: SecretEncryptor,
    ollama_base_url: str,
) -> tuple[str, str, str | None]:
    """Resolve ``(provider_id, base_url, api_key)`` from a credential.

    Loads the credential row (tenant-scoped), reads ``provider_id`` off the
    row, derives ``config_source`` from the catalog, and resolves the
    endpoint.  This is the single call site callers should use before picking
    an inference adapter — the credential is fetched once and ``provider_id``
    is derived once.

    Raises:
        NotFoundError: if the credential does not exist in the tenant.
        UnsupportedProviderError: if the credential's provider_id is unknown.
        ValidationError: if the base_url fails the SSRF check or is missing
            for an openai_compat credential.
    """
    row = await credentials_repo.get_credential(credential_id)
    provider_id = row.provider_id
    base_url, api_key = _resolve_url_and_key(provider_id, row, encryptor, ollama_base_url)
    return provider_id, base_url, api_key


