import httpx
import pytest

from tfm_rag.domain.value_objects.retrieval_iteration import LLMTextResponse, LLMToolCall
from tfm_rag.infrastructure.llm_providers.ollama import OllamaLLMAdapter
from tfm_rag.infrastructure.llm_providers.openai import OpenAILLMAdapter

# ---------------------------------------------------------------------------
# OpenAI-compat adapter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_adapter_captures_usage_text_response() -> None:
    """TokenUsage is populated on a plain-text response from the usage field."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hello", "tool_calls": None}}],
                "usage": {"prompt_tokens": 42, "completion_tokens": 7},
            },
        )

    resp = await OpenAILLMAdapter(transport=httpx.MockTransport(handler)).generate(
        base_url="http://x/v1",
        api_key="k",
        model_id="m",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        temperature=0.0,
        top_p=1.0,
        max_tokens=64,
    )
    assert isinstance(resp, LLMTextResponse)
    assert resp.usage is not None
    assert resp.usage.prompt_tokens == 42
    assert resp.usage.completion_tokens == 7


@pytest.mark.asyncio
async def test_openai_adapter_captures_usage_tool_call() -> None:
    """TokenUsage is populated on a tool-call response from the usage field."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "search_docs",
                                        "arguments": '{"query": "test"}',
                                    }
                                }
                            ]
                        }
                    }
                ],
                "usage": {"prompt_tokens": 55, "completion_tokens": 12},
            },
        )

    resp = await OpenAILLMAdapter(transport=httpx.MockTransport(handler)).generate(
        base_url="http://x/v1",
        api_key="k",
        model_id="m",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "search_docs", "parameters": {}}}],
        temperature=0.0,
        top_p=1.0,
        max_tokens=64,
    )
    assert isinstance(resp, LLMToolCall)
    assert resp.usage is not None
    assert resp.usage.prompt_tokens == 55
    assert resp.usage.completion_tokens == 12


@pytest.mark.asyncio
async def test_openai_adapter_usage_defaults_to_zero_when_absent() -> None:
    """Missing usage field yields TokenUsage(0, 0) not None."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    resp = await OpenAILLMAdapter(transport=httpx.MockTransport(handler)).generate(
        base_url="http://x/v1",
        api_key="k",
        model_id="m",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        temperature=0.0,
        top_p=1.0,
        max_tokens=64,
    )
    assert resp.usage is not None
    assert resp.usage.prompt_tokens == 0
    assert resp.usage.completion_tokens == 0


# ---------------------------------------------------------------------------
# Ollama adapter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_adapter_captures_usage_text_response() -> None:
    """TokenUsage is populated on a plain-text response from prompt_eval_count/eval_count."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "hello"},
                "done": True,
                "prompt_eval_count": 30,
                "eval_count": 11,
            },
        )

    resp = await OllamaLLMAdapter(transport=httpx.MockTransport(handler)).generate(
        base_url="http://y",
        api_key=None,
        model_id="llama3.1",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        temperature=0.0,
        top_p=1.0,
        max_tokens=64,
    )
    assert isinstance(resp, LLMTextResponse)
    assert resp.usage is not None
    assert resp.usage.prompt_tokens == 30
    assert resp.usage.completion_tokens == 11


@pytest.mark.asyncio
async def test_ollama_adapter_captures_usage_tool_call() -> None:
    """TokenUsage is populated on a tool-call response from prompt_eval_count/eval_count."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "search_docs",
                                "arguments": {"query": "test"},
                            }
                        }
                    ],
                },
                "done": True,
                "prompt_eval_count": 80,
                "eval_count": 20,
            },
        )

    resp = await OllamaLLMAdapter(transport=httpx.MockTransport(handler)).generate(
        base_url="http://y",
        api_key=None,
        model_id="llama3.1",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "search_docs", "parameters": {}}}],
        temperature=0.0,
        top_p=1.0,
        max_tokens=64,
    )
    assert isinstance(resp, LLMToolCall)
    assert resp.usage is not None
    assert resp.usage.prompt_tokens == 80
    assert resp.usage.completion_tokens == 20


@pytest.mark.asyncio
async def test_ollama_adapter_usage_defaults_to_zero_when_absent() -> None:
    """Missing prompt_eval_count/eval_count yields TokenUsage(0, 0) not None."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "ok"},
                "done": True,
            },
        )

    resp = await OllamaLLMAdapter(transport=httpx.MockTransport(handler)).generate(
        base_url="http://y",
        api_key=None,
        model_id="llama3.1",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        temperature=0.0,
        top_p=1.0,
        max_tokens=64,
    )
    assert resp.usage is not None
    assert resp.usage.prompt_tokens == 0
    assert resp.usage.completion_tokens == 0
