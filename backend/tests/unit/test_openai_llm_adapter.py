import json

import httpx
import pytest

from tfm_rag.domain.errors.chat import LLMError, LLMTimeoutError
from tfm_rag.domain.value_objects.retrieval_iteration import LLMTextResponse, LLMToolCall
from tfm_rag.infrastructure.llm_providers.openai import (
    OpenAILLMAdapter,
    _normalize_messages_for_openai,
)

_TOOLS = [{"type": "function", "function": {"name": "search_docs", "parameters": {}}}]

# The three-tool agentic loop (mirrors domain/catalog/agent_tools.build_tool_schemas).
_AGENTIC_TOOLS = [
    {"type": "function", "function": {"name": "search_docs", "parameters": {}}},
    {"type": "function", "function": {"name": "final_answer", "parameters": {}}},
    {"type": "function", "function": {"name": "abstain", "parameters": {}}},
]


async def _generate_agentic(handler):  # noqa: ANN001
    return await _adapter(handler).generate(
        base_url="https://api.groq.com/openai/v1",
        api_key="gsk-test",
        model_id="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": "hi"}],
        tools=_AGENTIC_TOOLS,
        temperature=0.0,
        top_p=1.0,
        max_tokens=512,
    )


@pytest.mark.asyncio
async def test_recovers_tool_call_from_groq_tool_use_failed() -> None:
    """Groq llama-3.3-70b emits tool calls in Llama's native `<function=NAME{...}>`
    text format; Groq returns HTTP 400 `tool_use_failed` with the raw output in
    `failed_generation`. We recover the intended call locally (no extra tokens)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "Failed to call a function. Please adjust your prompt.",
                    "type": "invalid_request_error",
                    "code": "tool_use_failed",
                    "failed_generation": (
                        '<function=search_docs{"query": "photoelectric effect '
                        'ultraviolet catastrophe"}></function>'
                    ),
                }
            },
        )

    resp = await _generate_agentic(handler)
    assert isinstance(resp, LLMToolCall)
    assert resp.tool == "search_docs"
    assert resp.arguments == {
        "query": "photoelectric effect ultraviolet catastrophe"
    }


@pytest.mark.asyncio
async def test_recovers_tool_call_from_groq_validation_failed() -> None:
    """The other 400 variant: Groq mis-parses the native format and reports the
    whole `NAME{...}` string as the (unknown) tool name. Recover from the message."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": (
                        "tool call validation failed: attempted to call tool "
                        "'search_docs{\"query\": \"internet pharmacies origin\"}' "
                        "which was not in request.tools"
                    ),
                    "type": "invalid_request_error",
                    "code": "invalid_request_error",
                }
            },
        )

    resp = await _generate_agentic(handler)
    assert isinstance(resp, LLMToolCall)
    assert resp.tool == "search_docs"
    assert resp.arguments == {"query": "internet pharmacies origin"}


@pytest.mark.asyncio
async def test_recovers_final_answer_with_braces_in_args() -> None:
    """raw_decode must stop at the JSON object's own closing brace even when the
    answer text contains braces, and ignore the trailing `</function>`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": "tool_use_failed",
                    "failed_generation": (
                        '<function=final_answer{"answer": "The set {a, b} is '
                        'closed."}></function>'
                    ),
                }
            },
        )

    resp = await _generate_agentic(handler)
    assert isinstance(resp, LLMToolCall)
    assert resp.tool == "final_answer"
    assert resp.arguments == {"answer": "The set {a, b} is closed."}


@pytest.mark.asyncio
async def test_does_not_fabricate_unknown_tool_from_400() -> None:
    """A recovered name that is NOT a declared tool must NOT be fabricated into a
    call; the 400 still raises."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": "tool_use_failed",
                    "failed_generation": (
                        '<function=delete_everything{"target": "prod"}></function>'
                    ),
                }
            },
        )

    with pytest.raises(LLMError):
        await _generate_agentic(handler)


@pytest.mark.asyncio
async def test_retries_on_429_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"}, json={"error": "rate"})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "hello"}}]},
        )

    resp = await _adapter(handler).generate(
        base_url="https://api.groq.com/openai/v1",
        api_key="gsk-test",
        model_id="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        temperature=0.0,
        top_p=1.0,
        max_tokens=64,
    )
    assert calls["n"] == 2  # retried once after the 429
    assert isinstance(resp, LLMTextResponse)
    assert resp.text == "hello"


def test_normalize_messages_makes_tool_calls_openai_compliant() -> None:
    # Agentic-loop shape: dict arguments, no id/type, tool result without id.
    raw = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "search_docs", "arguments": {"query": "x"}}}
            ],
        },
        {"role": "tool", "name": "search_docs", "content": "chunks"},
    ]
    out = _normalize_messages_for_openai(raw)
    tc = out[2]["tool_calls"][0]
    assert tc["function"]["arguments"] == json.dumps({"query": "x"})  # string, not dict
    assert tc["type"] == "function"
    assert tc["id"]
    assert out[3]["tool_call_id"] == tc["id"]  # tool result paired by order
    # input not mutated
    assert raw[2]["tool_calls"][0]["function"]["arguments"] == {"query": "x"}


def _adapter(handler) -> OpenAILLMAdapter:  # noqa: ANN001
    return OpenAILLMAdapter(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_tool_call_is_parsed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer sk-test"
        body = json.loads(request.content)
        assert body["model"] == "gpt-4o-mini"
        assert body["tools"] == _TOOLS
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
                                        "arguments": '{"query": "hello"}',
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    resp = await _adapter(handler).generate(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_id="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        tools=_TOOLS,
        temperature=0.0,
        top_p=1.0,
        max_tokens=512,
    )
    assert isinstance(resp, LLMToolCall)
    assert resp.tool == "search_docs"
    assert resp.arguments == {"query": "hello"}


@pytest.mark.asyncio
async def test_plain_text_is_parsed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "the answer"}}]}
        )

    resp = await _adapter(handler).generate(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_id="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        temperature=0.0,
        top_p=1.0,
        max_tokens=512,
    )
    assert isinstance(resp, LLMTextResponse)
    assert resp.text == "the answer"


@pytest.mark.asyncio
async def test_http_error_raises_llmerror() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(LLMError):
        await _adapter(handler).generate(
            base_url="https://api.openai.com/v1",
            api_key="bad",
            model_id="gpt-4o-mini",
            messages=[],
            tools=None,
            temperature=0.0,
            top_p=1.0,
            max_tokens=512,
        )


@pytest.mark.asyncio
async def test_timeout_raises_llmtimeouterror() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    with pytest.raises(LLMTimeoutError):
        await _adapter(handler).generate(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model_id="gpt-4o-mini",
            messages=[],
            tools=None,
            temperature=0.0,
            top_p=1.0,
            max_tokens=512,
        )


@pytest.mark.asyncio
async def test_empty_tool_call_arguments_raise_llmerror() -> None:
    """An empty or whitespace-only tool_call arguments string must raise LLMError,
    not silently become {}."""

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
                                        "arguments": "",
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    with pytest.raises(LLMError, match="empty"):
        await _adapter(handler).generate(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model_id="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            tools=_TOOLS,
            temperature=0.0,
            top_p=1.0,
            max_tokens=512,
        )


@pytest.mark.asyncio
async def test_whitespace_tool_call_arguments_raise_llmerror() -> None:
    """Whitespace-only tool_call arguments must also raise LLMError."""

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
                                        "arguments": "   ",
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    with pytest.raises(LLMError, match="empty"):
        await _adapter(handler).generate(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model_id="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            tools=_TOOLS,
            temperature=0.0,
            top_p=1.0,
            max_tokens=512,
        )
