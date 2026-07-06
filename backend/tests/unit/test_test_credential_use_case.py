"""Unit tests for test_credential use case (application/integrations/test_credential.py)."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

import tfm_rag.application.integrations.test_credential as _uc
from tfm_rag.application.integrations.test_credential import TestCredentialResult
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.errors.integrations import CredentialNotFoundError
from tfm_rag.infrastructure.persistence.repository import RequestContext


def _ctx() -> RequestContext:
    return RequestContext(tenant_id=uuid4(), user_id=uuid4())


def _make_row(
    provider_id: str = "openai",
    api_key_encrypted: bytes = b"encrypted-key",
    base_url: str | None = None,
) -> MagicMock:
    row = MagicMock()
    row.provider_id = provider_id
    row.api_key_encrypted = api_key_encrypted
    row.base_url = base_url
    return row


# ---------------------------------------------------------------------------
# test_credential happy-path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credential_happy_path_returns_ok() -> None:
    """Valid credential, provider returns 200 → result.ok is True."""
    session = MagicMock()
    ctx = _ctx()
    encryptor = MagicMock()
    encryptor.decrypt.return_value = b"sk-test-key"
    credential_id = uuid4()

    row = _make_row(provider_id="openai")
    repo_mock = MagicMock()
    repo_mock.get = AsyncMock(return_value=row)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status = MagicMock()

    with patch(
        "tfm_rag.application.integrations.test_credential.ProviderCredentialRepository",
        return_value=repo_mock,
    ), patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _uc.test_credential(
            session,
            ctx,
            encryptor,
            credential_id=credential_id,
            model_id="gpt-4o",
        )

    assert isinstance(result, TestCredentialResult)
    assert result.ok is True
    assert result.error is None
    assert result.latency_ms >= 0
    encryptor.decrypt.assert_called_once_with(row.api_key_encrypted)


# ---------------------------------------------------------------------------
# test_credential provider returns an HTTP error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credential_provider_http_error_returns_not_ok() -> None:
    """Provider returns 401 → result.ok is False and error is set."""
    session = MagicMock()
    ctx = _ctx()
    encryptor = MagicMock()
    encryptor.decrypt.return_value = b"bad-key"
    credential_id = uuid4()

    row = _make_row(provider_id="openai")
    repo_mock = MagicMock()
    repo_mock.get = AsyncMock(return_value=row)

    with patch(
        "tfm_rag.application.integrations.test_credential.ProviderCredentialRepository",
        return_value=repo_mock,
    ), patch("httpx.AsyncClient") as mock_client_cls:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 401
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Client error '401 Unauthorized' for url 'https://api.openai.com/v1/models'",
                request=MagicMock(),
                response=resp,
            )
        )
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _uc.test_credential(
            session,
            ctx,
            encryptor,
            credential_id=credential_id,
            model_id="gpt-4o",
        )

    assert result.ok is False
    assert result.error is not None
    # Friendly message, not the raw httpx string with the URL.
    assert "401" in result.error
    assert "Clave inválida" in result.error
    assert "https://" not in result.error
    assert result.latency_ms >= 0


# ---------------------------------------------------------------------------
# test_credential network timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credential_network_timeout_returns_not_ok() -> None:
    """Network timeout → result.ok is False with error message."""
    session = MagicMock()
    ctx = _ctx()
    encryptor = MagicMock()
    encryptor.decrypt.return_value = b"sk-key"
    credential_id = uuid4()

    row = _make_row(provider_id="openai_compat", base_url="https://api.example.com/v1")
    repo_mock = MagicMock()
    repo_mock.get = AsyncMock(return_value=row)

    with patch(
        "tfm_rag.application.integrations.test_credential.ProviderCredentialRepository",
        return_value=repo_mock,
    ), patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _uc.test_credential(
            session,
            ctx,
            encryptor,
            credential_id=credential_id,
            model_id="some-model",
        )

    assert result.ok is False
    assert result.error is not None
    assert "timeout" in result.error.lower()


# ---------------------------------------------------------------------------
# test_credential credential not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credential_not_found_raises() -> None:
    """repo.get raises → CredentialNotFoundError is re-raised."""
    session = MagicMock()
    ctx = _ctx()
    encryptor = MagicMock()
    credential_id = uuid4()

    repo_mock = MagicMock()
    repo_mock.get = AsyncMock(side_effect=Exception("row not found"))

    with patch(
        "tfm_rag.application.integrations.test_credential.ProviderCredentialRepository",
        return_value=repo_mock,
    ), pytest.raises(CredentialNotFoundError, match="row not found"):
        await _uc.test_credential(
            session,
            ctx,
            encryptor,
            credential_id=credential_id,
            model_id="gpt-4o",
        )


# ---------------------------------------------------------------------------
# test_credential openai_compat uses provided base_url
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credential_openai_compat_uses_base_url() -> None:
    """openai_compat provider uses the stored base_url rather than the default."""
    session = MagicMock()
    ctx = _ctx()
    encryptor = MagicMock()
    encryptor.decrypt.return_value = b"sk-compat-key"
    credential_id = uuid4()

    custom_base = "https://api.groq.com/openai/v1"
    row = _make_row(provider_id="openai_compat", base_url=custom_base)
    repo_mock = MagicMock()
    repo_mock.get = AsyncMock(return_value=row)

    captured_url: list[str] = []

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status = MagicMock()

    async def fake_get(url: str, **kwargs):  # type: ignore[no-untyped-def]
        captured_url.append(url)
        return mock_response

    with patch(
        "tfm_rag.application.integrations.test_credential.ProviderCredentialRepository",
        return_value=repo_mock,
    ), patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = fake_get
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _uc.test_credential(
            session,
            ctx,
            encryptor,
            credential_id=credential_id,
            model_id="llama3-70b",
        )

    assert result.ok is True
    assert len(captured_url) == 1
    assert captured_url[0].startswith(custom_base.rstrip("/"))


# ---------------------------------------------------------------------------
# test_credential openai provider always uses hardcoded base URL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credential_openai_ignores_stored_base_url() -> None:
    """Even if base_url is stored, openai provider always calls api.openai.com."""
    session = MagicMock()
    ctx = _ctx()
    encryptor = MagicMock()
    encryptor.decrypt.return_value = b"sk-real-key"
    credential_id = uuid4()

    row = _make_row(provider_id="openai", base_url="https://should-be-ignored.com/v1")
    repo_mock = MagicMock()
    repo_mock.get = AsyncMock(return_value=row)

    captured_url: list[str] = []

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status = MagicMock()

    async def fake_get(url: str, **kwargs):  # type: ignore[no-untyped-def]
        captured_url.append(url)
        return mock_response

    with patch(
        "tfm_rag.application.integrations.test_credential.ProviderCredentialRepository",
        return_value=repo_mock,
    ), patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = fake_get
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _uc.test_credential(
            session,
            ctx,
            encryptor,
            credential_id=credential_id,
            model_id="gpt-4o",
        )

    assert result.ok is True
    assert len(captured_url) == 1
    assert "api.openai.com" in captured_url[0]


# ---------------------------------------------------------------------------
# test_credential private base_url raises ValidationError before HTTP call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credential_private_base_url_raises_validation_error() -> None:
    """SSRF guard: a private base_url raises ValidationError, not a network call."""
    session = MagicMock()
    ctx = _ctx()
    encryptor = MagicMock()
    encryptor.decrypt.return_value = b"sk-key"
    credential_id = uuid4()

    row = _make_row(
        provider_id="openai_compat", base_url="http://192.168.1.100/v1"
    )
    repo_mock = MagicMock()
    repo_mock.get = AsyncMock(return_value=row)

    with patch(
        "tfm_rag.application.integrations.test_credential.ProviderCredentialRepository",
        return_value=repo_mock,
    ), pytest.raises(ValidationError, match="private"):
        await _uc.test_credential(
            session,
            ctx,
            encryptor,
            credential_id=credential_id,
            model_id="some-model",
        )
