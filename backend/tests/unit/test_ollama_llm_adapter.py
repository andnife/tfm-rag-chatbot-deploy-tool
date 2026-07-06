import json

import httpx
import pytest

from tfm_rag.domain.errors.chat import LLMError, LLMTimeoutError
from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMTextResponse,
    LLMToolCall,
)
from tfm_rag.infrastructure.llm_providers.ollama import OllamaLLMAdapter


def build_tool_schemas() -> list[dict]:
    """Three representative function-tool schemas. These transport tests only
    care that the adapter forwards `tools` into the request body — the schema
    contents are irrelevant — so we keep a local 3-tool list here rather than
    depend on a domain catalog.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for name in ("search_docs", "final_answer", "abstain")
    ]


def _mock_transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_ollama_returns_tool_call_when_response_has_tool_calls() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "model": "llama3.1",
                "created_at": "2026-05-24T00:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "search_docs",
                                "arguments": {"query": "what is X"},
                            },
                        }
                    ],
                },
                "done": True,
            },
        )

    adapter = OllamaLLMAdapter(transport=_mock_transport(handler))
    resp = await adapter.generate(
        base_url="http://ollama:11434",
        api_key=None,
        model_id="llama3.1",
        messages=[
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "what is X"},
        ],
        tools=build_tool_schemas(),
        temperature=0.2,
        top_p=1.0,
        max_tokens=1024,
    )

    assert isinstance(resp, LLMToolCall)
    assert resp.tool == "search_docs"
    assert resp.arguments == {"query": "what is X"}

    body = captured["body"]
    assert body["model"] == "llama3.1"
    assert body["stream"] is False
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "system"
    assert len(body["tools"]) == 3
    assert body["options"]["temperature"] == 0.2
    assert body["options"]["top_p"] == 1.0
    assert body["options"]["num_predict"] == 1024
    assert captured["url"].endswith("/api/chat")


@pytest.mark.asyncio
async def test_ollama_returns_text_response_when_no_tool_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "llama3.1",
                "message": {
                    "role": "assistant",
                    "content": "hello, I am a language model.",
                },
                "done": True,
            },
        )

    adapter = OllamaLLMAdapter(transport=_mock_transport(handler))
    resp = await adapter.generate(
        base_url="http://ollama:11434",
        api_key=None,
        model_id="llama3.1",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        temperature=0.2,
        top_p=1.0,
        max_tokens=1024,
    )

    assert isinstance(resp, LLMTextResponse)
    assert resp.text == "hello, I am a language model."


@pytest.mark.asyncio
async def test_ollama_parses_string_arguments_into_dict() -> None:
    """Some Ollama versions return tool arguments as a JSON-encoded string
    rather than a parsed object. The adapter MUST handle both shapes.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "llama3.1",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "final_answer",
                                "arguments": '{"answer": "X is a thing"}',
                            },
                        }
                    ],
                },
                "done": True,
            },
        )

    adapter = OllamaLLMAdapter(transport=_mock_transport(handler))
    resp = await adapter.generate(
        base_url="http://ollama:11434", api_key=None,
        model_id="llama3.1", messages=[{"role": "user", "content": "x"}],
        tools=build_tool_schemas(), temperature=0.2, top_p=1.0, max_tokens=512,
    )

    assert isinstance(resp, LLMToolCall)
    assert resp.tool == "final_answer"
    assert resp.arguments == {"answer": "X is a thing"}


@pytest.mark.asyncio
async def test_ollama_returns_text_when_tool_calls_is_empty_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "llama3.1",
                "message": {
                    "role": "assistant",
                    "content": "fallback text",
                    "tool_calls": [],
                },
                "done": True,
            },
        )

    adapter = OllamaLLMAdapter(transport=_mock_transport(handler))
    resp = await adapter.generate(
        base_url="http://ollama:11434", api_key=None,
        model_id="llama3.1", messages=[{"role": "user", "content": "x"}],
        tools=None, temperature=0.2, top_p=1.0, max_tokens=128,
    )
    assert isinstance(resp, LLMTextResponse)
    assert resp.text == "fallback text"


@pytest.mark.asyncio
async def test_ollama_raises_llm_error_on_http_500() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    adapter = OllamaLLMAdapter(transport=_mock_transport(handler))
    with pytest.raises(LLMError):
        await adapter.generate(
            base_url="http://ollama:11434", api_key=None,
            model_id="llama3.1", messages=[{"role": "user", "content": "x"}],
            tools=None, temperature=0.2, top_p=1.0, max_tokens=128,
        )


@pytest.mark.asyncio
async def test_ollama_raises_llm_timeout_error_on_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow", request=request)

    adapter = OllamaLLMAdapter(transport=_mock_transport(handler))
    with pytest.raises(LLMTimeoutError):
        await adapter.generate(
            base_url="http://ollama:11434", api_key=None,
            model_id="llama3.1", messages=[{"role": "user", "content": "x"}],
            tools=None, temperature=0.2, top_p=1.0, max_tokens=128,
        )


@pytest.mark.asyncio
async def test_ollama_raises_llm_error_on_malformed_response() -> None:
    """Body is JSON but doesn't have the expected `message` field."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"oops": "no message field"})

    adapter = OllamaLLMAdapter(transport=_mock_transport(handler))
    with pytest.raises(LLMError):
        await adapter.generate(
            base_url="http://ollama:11434", api_key=None,
            model_id="llama3.1", messages=[{"role": "user", "content": "x"}],
            tools=None, temperature=0.2, top_p=1.0, max_tokens=128,
        )


@pytest.mark.asyncio
async def test_ollama_omits_tools_field_when_none() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "x"},
                "done": True,
            },
        )

    adapter = OllamaLLMAdapter(transport=_mock_transport(handler))
    await adapter.generate(
        base_url="http://ollama:11434", api_key=None,
        model_id="llama3.1", messages=[{"role": "user", "content": "x"}],
        tools=None, temperature=0.2, top_p=1.0, max_tokens=128,
    )

    assert "tools" not in captured["body"]
