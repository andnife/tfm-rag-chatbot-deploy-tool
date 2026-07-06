import json
import logging
import os
import re
from typing import Any

import httpx

from tfm_rag.domain.errors.chat import LLMError, LLMTimeoutError
from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMResponse,
    LLMTextResponse,
    LLMToolCall,
    TokenUsage,
)

# Patterns that indicate an embedding model (case-insensitive).
# Mirrored from list_credential_models.py — lifted here so listing and
# inference share the same adapter.
_EMBEDDING_PATTERNS = re.compile(
    r"embed|bge|nomic|(gemma[^/]*embedding)",
    re.IGNORECASE,
)


def _kind_from_name(name: str) -> str:
    """Classify an Ollama model name as 'embedding' or 'llm' by heuristic."""
    if _EMBEDDING_PATTERNS.search(name):
        return "embedding"
    return "llm"

_log = logging.getLogger(__name__)

# Ollama defaults to a 2048-token context window, which silently truncates RAG
# prompts (5 retrieved chunks + system prompt + history routinely exceed it),
# crippling grounded answers. Set an explicit, larger window. Override via
# OLLAMA_NUM_CTX; larger values cost more RAM and are slower on CPU.
_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))


class OllamaLLMAdapter:
    """LLMProvider for Ollama's /api/chat with tool calling.

    Tool calling is supported by Ollama 0.4+ for llama3.1, mistral-nemo,
    and a growing list of models. The request shape mirrors OpenAI's
    Chat Completions (messages + tools); the response includes a
    `message.tool_calls` array when the model decided to invoke a tool.

    `transport` is an optional httpx Transport for testing (MockTransport
    in unit tests). When omitted, httpx uses its default async transport.
    """

    # Per-request timeout (seconds). Override via OLLAMA_TIMEOUT — CPU inference
    # of larger models can exceed the 300s default.
    DEFAULT_TIMEOUT_SECS = float(os.environ.get("OLLAMA_TIMEOUT", "300"))

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
                "num_ctx": _NUM_CTX,
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

        usage = TokenUsage(
            prompt_tokens=int(payload.get("prompt_eval_count", 0)),
            completion_tokens=int(payload.get("eval_count", 0)),
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
            return LLMToolCall(tool=name, arguments=arguments, usage=usage)

        content = message.get("content")
        if not isinstance(content, str):
            raise LLMError(
                f"Ollama message had no tool_calls and no string content: "
                f"{message!r}"
            )
        return LLMTextResponse(text=content, usage=usage)

    async def list_models(
        self,
        *,
        base_url: str,
        api_key: str | None,  # noqa: ARG002 — Ollama is keyless
    ) -> list[dict[str, object]]:
        """Return available models from Ollama's /api/tags endpoint.

        Raises LLMError on upstream failures (non-200, network, JSON parse
        errors). Kind heuristic: names matching embed|bge|nomic|gemma*embedding
        are classified as 'embedding'; everything else as 'llm'.
        """
        try:
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=10.0,
                transport=self._transport,
            ) as client:
                r = await client.get("/api/tags")
        except httpx.HTTPError as exc:
            raise LLMError(
                f"Ollama /api/tags transport failed: {exc}"
            ) from exc

        if r.status_code != 200:
            raise LLMError(
                f"Ollama /api/tags returned HTTP {r.status_code}: {r.text[:500]}"
            )

        try:
            data = r.json()
        except json.JSONDecodeError as exc:
            raise LLMError(
                f"Ollama /api/tags returned non-JSON body: {r.text[:200]}"
            ) from exc

        return [
            {"id": m.get("name", ""), "kind": _kind_from_name(m.get("name", ""))}
            for m in data.get("models", [])
            if m.get("name")
        ]
