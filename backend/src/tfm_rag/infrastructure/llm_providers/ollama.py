import json
import logging
from typing import Any

import httpx

from tfm_rag.domain.errors.chat import LLMError, LLMTimeoutError
from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMResponse,
    LLMTextResponse,
    LLMToolCall,
)

_log = logging.getLogger(__name__)


class OllamaLLMAdapter:
    """LLMProvider for Ollama's /api/chat with tool calling.

    Tool calling is supported by Ollama 0.4+ for llama3.1, mistral-nemo,
    and a growing list of models. The request shape mirrors OpenAI's
    Chat Completions (messages + tools); the response includes a
    `message.tool_calls` array when the model decided to invoke a tool.

    `transport` is an optional httpx Transport for testing (MockTransport
    in unit tests). When omitted, httpx uses its default async transport.
    """

    DEFAULT_TIMEOUT_SECS = 300.0

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float | None = None,
    ) -> None:
        self._transport = transport
        self._timeout = timeout or self.DEFAULT_TIMEOUT_SECS

    async def generate(
        self,
        *,
        base_url: str,
        api_key: str | None,  # noqa: ARG002 — Ollama is keyless
        model_id: str,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None,
        temperature: float,
        top_p: float,
        max_tokens: int,
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": top_p,
                "num_predict": max_tokens,
            },
        }
        if tools is not None:
            body["tools"] = tools

        try:
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                r = await client.post("/api/chat", json=body)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"Ollama /api/chat timed out after {self._timeout}s "
                f"(model={model_id!r})"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(
                f"Ollama /api/chat transport failed (model={model_id!r}): {exc}"
            ) from exc

        if r.status_code != 200:
            raise LLMError(
                f"Ollama /api/chat returned HTTP {r.status_code}: {r.text[:500]}"
            )

        try:
            payload = r.json()
        except json.JSONDecodeError as exc:
            raise LLMError(
                f"Ollama /api/chat returned non-JSON body: {r.text[:200]}"
            ) from exc

        message = payload.get("message")
        if not isinstance(message, dict):
            raise LLMError(
                f"Ollama /api/chat returned no `message` field; got keys "
                f"{list(payload)}"
            )

        tool_calls = message.get("tool_calls")
        if tool_calls:
            first = tool_calls[0]
            fn = first.get("function") or {}
            name = fn.get("name")
            if not isinstance(name, str):
                raise LLMError(
                    f"Ollama tool_call missing string `name`: {first!r}"
                )
            raw_args = fn.get("arguments", {})
            if isinstance(raw_args, str):
                try:
                    arguments: dict[str, Any] = json.loads(raw_args)
                except json.JSONDecodeError as exc:
                    raise LLMError(
                        f"Ollama tool_call arguments were a string but not "
                        f"valid JSON: {raw_args!r}"
                    ) from exc
            elif isinstance(raw_args, dict):
                arguments = raw_args
            else:
                raise LLMError(
                    f"Ollama tool_call arguments had unexpected type "
                    f"{type(raw_args).__name__}: {raw_args!r}"
                )
            return LLMToolCall(tool=name, arguments=arguments)

        content = message.get("content")
        if not isinstance(content, str):
            raise LLMError(
                f"Ollama message had no tool_calls and no string content: "
                f"{message!r}"
            )
        return LLMTextResponse(text=content)
