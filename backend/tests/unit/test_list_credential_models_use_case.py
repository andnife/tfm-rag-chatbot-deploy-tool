"""Unit tests for list_credential_models use-case.

Mocks at the adapter/resolver boundary:
  - ``resolve_inference_target`` is patched to return a (provider_id, base_url, api_key)
    tuple without touching the DB.
  - The adapter's ``list_models`` method is patched to return model lists or raise
    ``LLMError``, isolating the use-case logic from HTTP details.
"""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

import tfm_rag.application.integrations.list_credential_models as _uc  # noqa: E402
from tfm_rag.domain.errors.chat import LLMError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.infrastructure.persistence.repository import RequestContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx() -> RequestContext:
    return RequestContext(tenant_id=uuid4(), user_id=uuid4())


def _make_settings(ollama_base_url: str = "http://localhost:11434") -> MagicMock:
    s = MagicMock()
    s.ollama_base_url = ollama_base_url
    return s


def _make_encryptor() -> MagicMock:
    enc = MagicMock()
    return enc


def _make_adapter(
    models: list[dict] | None = None, raise_exc: Exception | None = None
) -> MagicMock:
    """Return a mock adapter whose list_models either returns models or raises."""
    adapter = MagicMock()
    if raise_exc is not None:
        adapter.list_models = AsyncMock(side_effect=raise_exc)
    else:
        adapter.list_models = AsyncMock(return_value=models or [])
    return adapter


# ---------------------------------------------------------------------------
# Test 1 – Ollama provider → llm + embedding kinds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_returns_llm_and_embedding_kinds() -> None:
    """resolve_inference_target returns ollama; adapter returns classified models."""
    session = MagicMock()
    ctx = _ctx()
    credential_id = uuid4()

    ollama_models = [
        {"id": "llama3.1", "kind": "llm"},
        {"id": "bge-m3", "kind": "embedding"},
    ]
    adapter = _make_adapter(models=ollama_models)

    with patch(
        "tfm_rag.application.integrations.list_credential_models.ProviderCredentialRepository",
    ), patch(
        "tfm_rag.application.integrations.list_credential_models.resolve_inference_target",
        new=AsyncMock(return_value=("ollama", "http://localhost:11434", None)),
    ), patch(
        "tfm_rag.application.integrations.list_credential_models.LLMDispatcher"
    ) as mock_dispatcher_cls:
        mock_dispatcher_cls.default.return_value.for_provider.return_value = adapter
        result = await _uc.list_credential_models(
            session,
            ctx,
            credential_id,
            encryptor=_make_encryptor(),
            settings=_make_settings(),
        )

    assert result["error"] is None
    assert len(result["models"]) == 2
    by_id = {m["id"]: m for m in result["models"]}
    assert by_id["llama3.1"]["kind"] == "llm"
    assert by_id["bge-m3"]["kind"] == "embedding"

    # Dispatcher was called with the correct provider_id
    mock_dispatcher_cls.default.return_value.for_provider.assert_called_once_with("ollama")
    # Adapter list_models was called with resolved endpoint
    adapter.list_models.assert_awaited_once_with(
        base_url="http://localhost:11434", api_key=None
    )


# ---------------------------------------------------------------------------
# Test 2 – openai_compat provider → unknown kind
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_compat_returns_unknown_kind() -> None:
    """resolve_inference_target returns openai_compat; adapter returns unknown-kind models."""
    session = MagicMock()
    ctx = _ctx()
    credential_id = uuid4()

    compat_models = [
        {"id": "deepseek-v4", "kind": "unknown"},
        {"id": "llama-3.3-70b", "kind": "unknown"},
    ]
    adapter = _make_adapter(models=compat_models)

    with patch(
        "tfm_rag.application.integrations.list_credential_models.ProviderCredentialRepository",
    ), patch(
        "tfm_rag.application.integrations.list_credential_models.resolve_inference_target",
        new=AsyncMock(
            return_value=("openai_compat", "https://api.groq.com/openai/v1", "sk-groq-key")
        ),
    ), patch(
        "tfm_rag.application.integrations.list_credential_models.LLMDispatcher"
    ) as mock_dispatcher_cls:
        mock_dispatcher_cls.default.return_value.for_provider.return_value = adapter
        result = await _uc.list_credential_models(
            session,
            ctx,
            credential_id,
            encryptor=_make_encryptor(),
            settings=_make_settings(),
        )

    assert result["error"] is None
    assert len(result["models"]) == 2
    for m in result["models"]:
        assert m["kind"] == "unknown"
    ids = [m["id"] for m in result["models"]]
    assert "deepseek-v4" in ids
    assert "llama-3.3-70b" in ids

    mock_dispatcher_cls.default.return_value.for_provider.assert_called_once_with("openai_compat")
    adapter.list_models.assert_awaited_once_with(
        base_url="https://api.groq.com/openai/v1", api_key="sk-groq-key"
    )


# ---------------------------------------------------------------------------
# Test 3 – adapter raises LLMError → {models:[], error:<nonempty>}, no exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adapter_llm_error_returns_error_dict_not_exception() -> None:
    """LLMError from adapter.list_models → {models:[], error} with no propagation."""
    session = MagicMock()
    ctx = _ctx()
    credential_id = uuid4()

    adapter = _make_adapter(raise_exc=LLMError("upstream returned HTTP 500: internal error"))

    with patch(
        "tfm_rag.application.integrations.list_credential_models.ProviderCredentialRepository",
    ), patch(
        "tfm_rag.application.integrations.list_credential_models.resolve_inference_target",
        new=AsyncMock(
            return_value=("openai_compat", "https://api.groq.com/openai/v1", "sk-key")
        ),
    ), patch(
        "tfm_rag.application.integrations.list_credential_models.LLMDispatcher"
    ) as mock_dispatcher_cls:
        mock_dispatcher_cls.default.return_value.for_provider.return_value = adapter
        result = await _uc.list_credential_models(
            session,
            ctx,
            credential_id,
            encryptor=_make_encryptor(),
            settings=_make_settings(),
        )

    assert result["models"] == []
    assert result["error"]  # non-empty string
    assert "500" in result["error"] or "upstream" in result["error"]


# ---------------------------------------------------------------------------
# Test 4 – network-level LLMError → {models:[], error:<nonempty>}, no exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adapter_network_llm_error_returns_error_dict_not_exception() -> None:
    """Network LLMError from adapter → {models:[], error} with no propagation."""
    session = MagicMock()
    ctx = _ctx()
    credential_id = uuid4()

    adapter = _make_adapter(raise_exc=LLMError("transport failed: connection refused"))

    with patch(
        "tfm_rag.application.integrations.list_credential_models.ProviderCredentialRepository",
    ), patch(
        "tfm_rag.application.integrations.list_credential_models.resolve_inference_target",
        new=AsyncMock(
            return_value=("openai_compat", "https://api.groq.com/openai/v1", "sk-key")
        ),
    ), patch(
        "tfm_rag.application.integrations.list_credential_models.LLMDispatcher"
    ) as mock_dispatcher_cls:
        mock_dispatcher_cls.default.return_value.for_provider.return_value = adapter
        result = await _uc.list_credential_models(
            session,
            ctx,
            credential_id,
            encryptor=_make_encryptor(),
            settings=_make_settings(),
        )

    assert result["models"] == []
    assert result["error"]  # non-empty string


# ---------------------------------------------------------------------------
# Test 5 – unknown credential id → NotFoundError propagates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_credential_raises_not_found_error() -> None:
    """Missing/cross-tenant credential → resolve_inference_target raises NotFoundError."""
    session = MagicMock()
    ctx = _ctx()
    credential_id = uuid4()

    with patch(
        "tfm_rag.application.integrations.list_credential_models.ProviderCredentialRepository",
    ), patch(
        "tfm_rag.application.integrations.list_credential_models.resolve_inference_target",
        new=AsyncMock(side_effect=NotFoundError("ProviderCredentialRow not found")),
    ), pytest.raises(NotFoundError):
        await _uc.list_credential_models(
            session,
            ctx,
            credential_id,
            encryptor=_make_encryptor(),
            settings=_make_settings(),
        )


# ---------------------------------------------------------------------------
# Test 6 – DB error from resolve_inference_target propagates (not masked as 404)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_error_propagates_not_masked_as_not_found() -> None:
    """A DB-level RuntimeError from resolve_inference_target must propagate (not be masked)."""
    session = MagicMock()
    ctx = _ctx()

    with patch(
        "tfm_rag.application.integrations.list_credential_models.ProviderCredentialRepository",
    ), patch(
        "tfm_rag.application.integrations.list_credential_models.resolve_inference_target",
        new=AsyncMock(side_effect=RuntimeError("connection reset")),
    ), pytest.raises(RuntimeError):
        await _uc.list_credential_models(
            session,
            ctx,
            uuid4(),
            encryptor=_make_encryptor(),
            settings=_make_settings(),
        )


# ---------------------------------------------------------------------------
# Test 7 – error message is truncated to 200 chars
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_message_truncated_to_200_chars() -> None:
    """LLMError message longer than 200 chars is truncated in the result."""
    session = MagicMock()
    ctx = _ctx()
    long_message = "x" * 500
    adapter = _make_adapter(raise_exc=LLMError(long_message))

    with patch(
        "tfm_rag.application.integrations.list_credential_models.ProviderCredentialRepository",
    ), patch(
        "tfm_rag.application.integrations.list_credential_models.resolve_inference_target",
        new=AsyncMock(return_value=("openai_compat", "https://api.example.com/v1", "sk-key")),
    ), patch(
        "tfm_rag.application.integrations.list_credential_models.LLMDispatcher"
    ) as mock_dispatcher_cls:
        mock_dispatcher_cls.default.return_value.for_provider.return_value = adapter
        result = await _uc.list_credential_models(
            session,
            ctx,
            uuid4(),
            encryptor=_make_encryptor(),
            settings=_make_settings(),
        )

    assert result["models"] == []
    assert len(result["error"]) <= 200
