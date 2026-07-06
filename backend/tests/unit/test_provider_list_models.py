"""Unit tests for list_models() on LLM provider adapters.

Tests follow the MockTransport pattern established in test_openai_llm_adapter.py
and test_llm_adapters_usage.py.

Upstream-failure contract: adapters RAISE on upstream failure (non-200, network,
JSON parse errors). The use-case layer (Task 5) owns the no-5xx contract by
catching these and returning {"models": [], "error": ...}.
"""

import httpx
import pytest

from tfm_rag.domain.errors.chat import LLMError
from tfm_rag.infrastructure.llm_providers.dispatcher import LLMDispatcher
from tfm_rag.infrastructure.llm_providers.ollama import OllamaLLMAdapter
from tfm_rag.infrastructure.llm_providers.openai import OpenAILLMAdapter

# ---------------------------------------------------------------------------
# OllamaLLMAdapter.list_models
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_list_models_returns_llm_and_embedding_kinds() -> None:
    """Ollama /api/tags response is parsed; kind heuristic classifies models."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "llama3.1"},
                    {"name": "bge-m3"},
                ]
            },
        )

    adapter = OllamaLLMAdapter(transport=httpx.MockTransport(handler))
    result = await adapter.list_models(base_url="http://localhost:11434", api_key=None)

    assert result == [
        {"id": "llama3.1", "kind": "llm"},
        {"id": "bge-m3", "kind": "embedding"},
    ]


@pytest.mark.asyncio
async def test_ollama_list_models_embedding_heuristics() -> None:
    """All embedding-heuristic patterns are correctly classified."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "nomic-embed-text"},
                    {"name": "bge-large"},
                    {"name": "mxbai-embed-large"},
                    {"name": "gemma-embedding"},
                    {"name": "llama3.2"},
                    {"name": "mistral"},
                ]
            },
        )

    adapter = OllamaLLMAdapter(transport=httpx.MockTransport(handler))
    result = await adapter.list_models(base_url="http://localhost:11434", api_key=None)

    kinds = {m["id"]: m["kind"] for m in result}
    assert kinds["nomic-embed-text"] == "embedding"
    assert kinds["bge-large"] == "embedding"
    assert kinds["mxbai-embed-large"] == "embedding"
    assert kinds["gemma-embedding"] == "embedding"
    assert kinds["llama3.2"] == "llm"
    assert kinds["mistral"] == "llm"


@pytest.mark.asyncio
async def test_ollama_list_models_upstream_500_raises() -> None:
    """A non-200 response from Ollama raises LLMError (not returns empty list)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    adapter = OllamaLLMAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError):
        await adapter.list_models(base_url="http://localhost:11434", api_key=None)


@pytest.mark.asyncio
async def test_ollama_list_models_network_error_raises() -> None:
    """A transport-level error from Ollama raises LLMError."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    adapter = OllamaLLMAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError):
        await adapter.list_models(base_url="http://localhost:11434", api_key=None)


@pytest.mark.asyncio
async def test_ollama_list_models_empty_models_list() -> None:
    """Empty models array returns an empty list without error."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": []})

    adapter = OllamaLLMAdapter(transport=httpx.MockTransport(handler))
    result = await adapter.list_models(base_url="http://localhost:11434", api_key=None)
    assert result == []


# ---------------------------------------------------------------------------
# OpenAILLMAdapter.list_models
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_list_models_returns_unknown_kind() -> None:
    """OpenAI /models endpoint is parsed; all models get kind='unknown'."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        assert request.headers["Authorization"] == "Bearer sk-test"
        return httpx.Response(
            200,
            json={"data": [{"id": "deepseek-v4"}]},
        )

    adapter = OpenAILLMAdapter(transport=httpx.MockTransport(handler))
    result = await adapter.list_models(
        base_url="https://api.example.com/v1", api_key="sk-test"
    )

    assert result == [{"id": "deepseek-v4", "kind": "unknown"}]


@pytest.mark.asyncio
async def test_openai_list_models_multiple_models() -> None:
    """Multiple models from OpenAI /models are all returned as unknown kind."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "gpt-4o"},
                    {"id": "gpt-4o-mini"},
                    {"id": "text-embedding-3-small"},
                ]
            },
        )

    adapter = OpenAILLMAdapter(transport=httpx.MockTransport(handler))
    result = await adapter.list_models(
        base_url="https://api.openai.com/v1", api_key="sk-key"
    )

    assert result == [
        {"id": "gpt-4o", "kind": "unknown"},
        {"id": "gpt-4o-mini", "kind": "unknown"},
        {"id": "text-embedding-3-small", "kind": "unknown"},
    ]


@pytest.mark.asyncio
async def test_openai_list_models_no_api_key_omits_auth_header() -> None:
    """When api_key is None, no Authorization header is sent."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "Authorization" not in request.headers
        return httpx.Response(200, json={"data": [{"id": "local-model"}]})

    adapter = OpenAILLMAdapter(transport=httpx.MockTransport(handler))
    result = await adapter.list_models(
        base_url="http://localhost:8000/v1", api_key=None
    )
    assert result == [{"id": "local-model", "kind": "unknown"}]


@pytest.mark.asyncio
async def test_openai_list_models_upstream_500_raises() -> None:
    """A non-200 response from OpenAI /models raises LLMError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    adapter = OpenAILLMAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError):
        await adapter.list_models(
            base_url="https://api.openai.com/v1", api_key="sk-key"
        )


@pytest.mark.asyncio
async def test_openai_list_models_network_error_raises() -> None:
    """A transport-level error from OpenAI raises LLMError."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    adapter = OpenAILLMAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError):
        await adapter.list_models(
            base_url="https://api.openai.com/v1", api_key="sk-key"
        )


@pytest.mark.asyncio
async def test_openai_list_models_empty_data_list() -> None:
    """Empty data array returns an empty list without error."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    adapter = OpenAILLMAdapter(transport=httpx.MockTransport(handler))
    result = await adapter.list_models(
        base_url="https://api.openai.com/v1", api_key="sk-key"
    )
    assert result == []


@pytest.mark.asyncio
async def test_openai_list_models_classifies_by_metadata_tags() -> None:
    """When the endpoint provides metadata.tags (e.g. DeepInfra), models are
    classified: embed→embedding, chat→llm, other/absent→unknown."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [
            {"id": "BAAI/bge-m3", "metadata": {"tags": ["embed"]}},
            {"id": "Qwen/Qwen2.5-72B-Instruct",
             "metadata": {"tags": ["chat", "reasoning"]}},
            {"id": "black-forest-labs/FLUX", "metadata": {"tags": ["image-gen"]}},
            {"id": "no-metadata-model"},
        ]})

    adapter = OpenAILLMAdapter(transport=httpx.MockTransport(handler))
    result = await adapter.list_models(
        base_url="https://api.deepinfra.com/v1/openai", api_key="k"
    )
    kinds = {m["id"]: m["kind"] for m in result}
    assert kinds["BAAI/bge-m3"] == "embedding"
    assert kinds["Qwen/Qwen2.5-72B-Instruct"] == "llm"
    assert kinds["black-forest-labs/FLUX"] == "unknown"
    assert kinds["no-metadata-model"] == "unknown"


# ---------------------------------------------------------------------------
# Dispatcher: lister_for resolves provider_id to the right adapter
# ---------------------------------------------------------------------------


def test_dispatcher_lister_for_ollama_returns_ollama_adapter() -> None:
    """Dispatcher resolves 'ollama' to OllamaLLMAdapter."""
    dispatcher = LLMDispatcher.default()
    adapter = dispatcher.for_provider("ollama")
    assert isinstance(adapter, OllamaLLMAdapter)


def test_dispatcher_lister_for_openai_returns_openai_adapter() -> None:
    """Dispatcher resolves 'openai' to OpenAILLMAdapter."""
    dispatcher = LLMDispatcher.default()
    adapter = dispatcher.for_provider("openai")
    assert isinstance(adapter, OpenAILLMAdapter)


def test_dispatcher_lister_for_openai_compat_returns_openai_adapter() -> None:
    """Dispatcher resolves 'openai_compat' to OpenAILLMAdapter (same instance)."""
    dispatcher = LLMDispatcher.default()
    adapter = dispatcher.for_provider("openai_compat")
    assert isinstance(adapter, OpenAILLMAdapter)
