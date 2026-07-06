"""Unit tests for upsert_provider_credential use case."""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tfm_rag.application.integrations.upsert_provider_credential import (
    UpsertResult,
    upsert_provider_credential,
)
from tfm_rag.domain.entities.provider_credential import ProviderCredential
from tfm_rag.domain.errors.common import ValidationError

_NOW = datetime.now(UTC)


def _credential(
    *,
    provider_id: str = "openai",
    label: str = "default",
    base_url: str | None = None,
    max_concurrency: int | None = None,
    min_request_interval_seconds: float | None = None,
) -> ProviderCredential:
    return ProviderCredential(
        id=uuid4(),
        tenant_id=uuid4(),
        provider_id=provider_id,
        label=label,
        api_key_encrypted=b"stored-encrypted",
        base_url=base_url,
        config_source="TENANT_CREDENTIAL",
        created_at=_NOW,
        updated_at=_NOW,
        max_concurrency=max_concurrency,
        min_request_interval_seconds=min_request_interval_seconds,
    )


def _make_repo(existing: ProviderCredential | None = None) -> MagicMock:
    repo = MagicMock()
    repo.find_by_provider_and_label = AsyncMock(return_value=existing)
    repo.create_credential = AsyncMock(
        side_effect=lambda **kw: _credential(
            provider_id=kw["provider_id"],
            label=kw["label"],
            base_url=kw["base_url"],
            max_concurrency=kw["max_concurrency"],
            min_request_interval_seconds=kw["min_request_interval_seconds"],
        )
    )
    return repo


# ---------------------------------------------------------------------------
# Happy path: create new credential (no existing row)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_creates_new_credential() -> None:
    """When no existing credential exists, a new one is created via the port."""
    repo = _make_repo(existing=None)
    encryptor = MagicMock()
    encryptor.encrypt.return_value = b"encrypted-api-key"

    result = await upsert_provider_credential(
        credentials_repo=repo,
        encryptor=encryptor,
        provider_id="openai",
        label="default",
        api_key="sk-test-key",
    )

    assert isinstance(result, UpsertResult)
    assert result.provider_id == "openai"
    assert result.label == "default"
    assert result.id is not None

    # Encryption boundary: encrypt called with plaintext bytes
    encryptor.encrypt.assert_called_once_with(b"sk-test-key")
    repo.create_credential.assert_awaited_once()
    assert repo.create_credential.call_args.kwargs["api_key_encrypted"] == b"encrypted-api-key"


# ---------------------------------------------------------------------------
# max_concurrency: stored on create + validated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_stores_max_concurrency() -> None:
    repo = _make_repo(existing=None)
    encryptor = MagicMock()
    encryptor.encrypt.return_value = b"enc"

    result = await upsert_provider_credential(
        credentials_repo=repo, encryptor=encryptor,
        provider_id="openai", label="default", api_key="sk", max_concurrency=6,
    )

    assert result.max_concurrency == 6
    assert repo.create_credential.call_args.kwargs["max_concurrency"] == 6


@pytest.mark.asyncio
async def test_upsert_rejects_nonpositive_max_concurrency() -> None:
    repo = _make_repo(existing=None)
    encryptor = MagicMock()
    with pytest.raises(ValidationError):
        await upsert_provider_credential(
            credentials_repo=repo, encryptor=encryptor,
            provider_id="openai", label="default", api_key="sk", max_concurrency=0,
        )
    repo.create_credential.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_stores_min_request_interval_seconds() -> None:
    repo = _make_repo(existing=None)
    encryptor = MagicMock()
    encryptor.encrypt.return_value = b"enc"

    result = await upsert_provider_credential(
        credentials_repo=repo, encryptor=encryptor,
        provider_id="openai", label="default", api_key="sk",
        min_request_interval_seconds=2.0,
    )
    assert result.min_request_interval_seconds == 2.0
    assert repo.create_credential.call_args.kwargs["min_request_interval_seconds"] == 2.0


@pytest.mark.asyncio
async def test_upsert_rejects_nonpositive_interval() -> None:
    repo = _make_repo(existing=None)
    encryptor = MagicMock()
    with pytest.raises(ValidationError):
        await upsert_provider_credential(
            credentials_repo=repo, encryptor=encryptor,
            provider_id="openai", label="default", api_key="sk",
            min_request_interval_seconds=0,
        )
    repo.create_credential.assert_not_called()


# ---------------------------------------------------------------------------
# Update path: existing credential is overwritten
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_updates_existing_credential() -> None:
    """When a matching credential exists, it is overwritten via update_credential."""
    existing = _credential(provider_id="openai", label="prod")
    repo = _make_repo(existing=existing)
    repo.update_credential = AsyncMock(
        return_value=_credential(provider_id="openai", label="prod")
    )
    encryptor = MagicMock()
    encryptor.encrypt.return_value = b"new-encrypted-key"

    result = await upsert_provider_credential(
        credentials_repo=repo,
        encryptor=encryptor,
        provider_id="openai",
        label="prod",
        api_key="sk-new-key",
    )

    assert isinstance(result, UpsertResult)
    assert result.provider_id == "openai"
    assert result.label == "prod"

    # Encryption boundary: plaintext bytes passed to encryptor
    encryptor.encrypt.assert_called_once_with(b"sk-new-key")
    repo.update_credential.assert_awaited_once_with(
        existing.id,
        api_key_encrypted=b"new-encrypted-key",
        base_url=None,
        max_concurrency=None,
        min_request_interval_seconds=None,
    )
    repo.create_credential.assert_not_called()


# ---------------------------------------------------------------------------
# Validation: unknown provider_id raises ValidationError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_unknown_provider_raises() -> None:
    """Supplying an unknown provider_id raises ValidationError before any repo access."""
    repo = _make_repo()
    encryptor = MagicMock()

    with pytest.raises(ValidationError, match="Unknown provider_id"):
        await upsert_provider_credential(
            credentials_repo=repo,
            encryptor=encryptor,
            provider_id="nonexistent_provider",
            label="x",
            api_key="key",
        )

    encryptor.encrypt.assert_not_called()
    repo.find_by_provider_and_label.assert_not_called()


# ---------------------------------------------------------------------------
# Validation: SERVER_ENV provider raises ValidationError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_server_env_provider_raises() -> None:
    """Provider configured via SERVER_ENV must not accept tenant credentials."""
    repo = _make_repo()
    encryptor = MagicMock()

    # "ollama" has config_source="SERVER_ENV"
    with pytest.raises(ValidationError, match="SERVER_ENV"):
        await upsert_provider_credential(
            credentials_repo=repo,
            encryptor=encryptor,
            provider_id="ollama",
            label="local",
            api_key="irrelevant",
        )

    encryptor.encrypt.assert_not_called()


# ---------------------------------------------------------------------------
# Validation: requires_base_url_input but none provided raises ValidationError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_missing_base_url_raises() -> None:
    """openai_compat requires a base_url; omitting it raises ValidationError."""
    repo = _make_repo()
    encryptor = MagicMock()

    with pytest.raises(ValidationError, match="base_url"):
        await upsert_provider_credential(
            credentials_repo=repo,
            encryptor=encryptor,
            provider_id="openai_compat",
            label="groq",
            api_key="sk-groq-key",
            base_url=None,
        )

    encryptor.encrypt.assert_not_called()


# ---------------------------------------------------------------------------
# Happy path: openai_compat with base_url succeeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_openai_compat_with_base_url_succeeds() -> None:
    """openai_compat with a valid base_url is created correctly."""
    repo = _make_repo(existing=None)
    encryptor = MagicMock()
    encryptor.encrypt.return_value = b"encrypted-compat-key"

    result = await upsert_provider_credential(
        credentials_repo=repo,
        encryptor=encryptor,
        provider_id="openai_compat",
        label="groq",
        api_key="sk-groq-key",
        base_url="https://api.groq.com/openai/v1",
    )

    assert result.provider_id == "openai_compat"
    assert result.label == "groq"
    encryptor.encrypt.assert_called_once_with(b"sk-groq-key")
    repo.create_credential.assert_awaited_once()


# ---------------------------------------------------------------------------
# Security: SSRF guard rejects a private/loopback base_url at save time
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_rejects_internal_base_url() -> None:
    """An internal/loopback base_url must be rejected before any repo write."""
    repo = _make_repo()
    encryptor = MagicMock()

    with pytest.raises(ValidationError, match="private"):
        await upsert_provider_credential(
            credentials_repo=repo,
            encryptor=encryptor,
            provider_id="openai_compat",
            label="evil",
            api_key="sk-x",
            base_url="http://127.0.0.1:8000/v1",
        )

    encryptor.encrypt.assert_not_called()


# ---------------------------------------------------------------------------
# Normalization: trailing slash is stripped from base_url before persisting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_normalizes_base_url_trailing_slash_on_create() -> None:
    """A base_url with trailing slashes is canonicalized before create."""
    repo = _make_repo(existing=None)
    encryptor = MagicMock()
    encryptor.encrypt.return_value = b"enc"

    await upsert_provider_credential(
        credentials_repo=repo,
        encryptor=encryptor,
        provider_id="openai_compat",
        label="groq",
        api_key="sk-groq-key",
        base_url="https://api.groq.com/openai/v1//",
    )

    assert (
        repo.create_credential.call_args.kwargs["base_url"]
        == "https://api.groq.com/openai/v1"
    )


@pytest.mark.asyncio
async def test_upsert_normalizes_base_url_trailing_slash_on_update() -> None:
    """On update, the stored base_url is canonicalized too."""
    existing = _credential(provider_id="openai_compat", label="groq")
    repo = _make_repo(existing=existing)
    repo.update_credential = AsyncMock(return_value=existing)
    encryptor = MagicMock()
    encryptor.encrypt.return_value = b"enc"

    await upsert_provider_credential(
        credentials_repo=repo,
        encryptor=encryptor,
        provider_id="openai_compat",
        label="groq",
        api_key="sk-groq-key",
        base_url="https://api.groq.com/openai/v1/",
    )

    assert (
        repo.update_credential.call_args.kwargs["base_url"]
        == "https://api.groq.com/openai/v1"
    )


# ---------------------------------------------------------------------------
# Lookup: existing credential resolved by (provider_id, label)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_looks_up_existing_by_provider_and_label() -> None:
    """The upsert must resolve the existing credential via the port's
    (provider_id, label) lookup — not a raw query."""
    repo = _make_repo(existing=None)
    encryptor = MagicMock()
    encryptor.encrypt.return_value = b"enc"

    await upsert_provider_credential(
        credentials_repo=repo,
        encryptor=encryptor,
        provider_id="openai",
        label="default",
        api_key="sk-key",
    )

    repo.find_by_provider_and_label.assert_awaited_once_with("openai", "default")


# ---------------------------------------------------------------------------
# Encryption boundary: update path passes correct plaintext to encryptor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_update_encrypts_new_plaintext() -> None:
    """On update, the NEW api_key plaintext (not old ciphertext) is encrypted."""
    existing = _credential()
    repo = _make_repo(existing=existing)
    repo.update_credential = AsyncMock(return_value=existing)
    encryptor = MagicMock()
    encryptor.encrypt.return_value = b"fresh-cipher"

    await upsert_provider_credential(
        credentials_repo=repo,
        encryptor=encryptor,
        provider_id="openai",
        label="default",
        api_key="brand-new-key",
    )

    # Must encrypt the exact new plaintext, not the old stored bytes
    encryptor.encrypt.assert_called_once_with(b"brand-new-key")
    assert repo.update_credential.call_args.kwargs["api_key_encrypted"] == b"fresh-cipher"
