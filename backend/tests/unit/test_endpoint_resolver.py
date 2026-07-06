from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from tfm_rag.application.integrations.endpoint_resolver import (
    resolve_inference_target,
)
from tfm_rag.domain.errors.common import NotFoundError, ValidationError


@dataclass
class _Row:
    api_key_encrypted: bytes
    base_url: str | None
    provider_id: str = "openai"  # added for resolve_inference_target tests


class _FakeRepo:
    def __init__(self, row: _Row | None) -> None:
        self._row = row
        self.get_called_with = None

    async def get_credential(self, credential_id: UUID):
        self.get_called_with = credential_id
        assert self._row is not None
        return self._row


class _RaisingRepo:
    """Repo that raises NotFoundError (simulates unknown / cross-tenant credential)."""

    async def get_credential(self, credential_id: UUID):
        raise NotFoundError(
            f"ProviderCredentialRow({credential_id}) not found in tenant"
        )


class _FakeEncryptor:
    def decrypt(self, ciphertext: bytes) -> bytes:
        return ciphertext  # identity, plaintext stored as-is in the fake


# ---------------------------------------------------------------------------
# resolve_inference_target tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rit_ollama_credential_returns_server_env_tuple() -> None:
    """ollama credential → ("ollama", ollama_base_url, None); repo NOT touched."""
    repo = _FakeRepo(_Row(api_key_encrypted=b"", base_url=None, provider_id="ollama"))
    provider_id, base_url, api_key = await resolve_inference_target(
        credential_id=uuid4(),
        ollama_base_url="http://localhost:11434",
        credentials_repo=repo,
        encryptor=_FakeEncryptor(),
    )
    assert provider_id == "ollama"
    assert base_url == "http://localhost:11434"
    assert api_key is None


@pytest.mark.asyncio
async def test_rit_openai_compat_credential_returns_row_base_url_and_decrypted_key() -> None:
    """openai_compat credential → ("openai_compat", row.base_url, decrypted_key)."""
    repo = _FakeRepo(
        _Row(
            api_key_encrypted=b"gsk-supersecret",
            base_url="https://api.groq.com/openai/v1",
            provider_id="openai_compat",
        )
    )
    provider_id, base_url, api_key = await resolve_inference_target(
        credential_id=uuid4(),
        ollama_base_url="http://localhost:11434",
        credentials_repo=repo,
        encryptor=_FakeEncryptor(),
    )
    assert provider_id == "openai_compat"
    assert base_url == "https://api.groq.com/openai/v1"
    assert api_key == "gsk-supersecret"


@pytest.mark.asyncio
async def test_rit_openai_credential_forces_public_base_url() -> None:
    """openai credential → ("openai", "https://api.openai.com/v1", decrypted_key)."""
    repo = _FakeRepo(
        _Row(api_key_encrypted=b"sk-openai", base_url=None, provider_id="openai")
    )
    provider_id, base_url, api_key = await resolve_inference_target(
        credential_id=uuid4(),
        ollama_base_url="http://localhost:11434",
        credentials_repo=repo,
        encryptor=_FakeEncryptor(),
    )
    assert provider_id == "openai"
    assert base_url == "https://api.openai.com/v1"
    assert api_key == "sk-openai"


@pytest.mark.asyncio
async def test_rit_unknown_credential_raises_not_found_error() -> None:
    """A missing/cross-tenant credential raises NotFoundError."""
    with pytest.raises(NotFoundError):
        await resolve_inference_target(
            credential_id=uuid4(),
            ollama_base_url="http://localhost:11434",
            credentials_repo=_RaisingRepo(),
            encryptor=_FakeEncryptor(),
        )


@pytest.mark.asyncio
async def test_rit_ssrf_rejection_still_applies() -> None:
    """openai_compat with a private base_url must still be rejected (SSRF)."""
    repo = _FakeRepo(
        _Row(
            api_key_encrypted=b"key",
            base_url="http://169.254.169.254/v1",
            provider_id="openai_compat",
        )
    )
    with pytest.raises(ValidationError):
        await resolve_inference_target(
            credential_id=uuid4(),
            ollama_base_url="http://localhost:11434",
            credentials_repo=repo,
            encryptor=_FakeEncryptor(),
        )
