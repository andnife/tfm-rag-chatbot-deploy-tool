import asyncio
import json
import logging
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

_log = logging.getLogger(__name__)


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header (seconds) into a float, if present."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _normalize_messages_for_openai(
    messages: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Make agentic tool-call messages strictly OpenAI-compliant.

    The agentic loop builds tool calls in Ollama's lax shape (``arguments`` as a
    dict, no ``id``/``type``, tool results without ``tool_call_id``). Strict
    endpoints (Groq, OpenAI) reject that, so for the OpenAI adapter we coerce
    ``arguments`` to a JSON string, add ``id``+``type`` to each tool call, and
    back-fill ``tool_call_id`` on the following tool message (paired by order).
    The input is not mutated.
    """
    out: list[dict[str, object]] = []
    last_tool_call_id: str | None = None
    for m in messages:
        m = dict(m)
        tool_calls = m.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            new_calls = []
            for j, tc in enumerate(tool_calls):
                tc = dict(tc)
                fn = dict(tc.get("function") or {})
                args = fn.get("arguments")
                if not isinstance(args, str):
                    fn["arguments"] = json.dumps(args if args is not None else {})
                tc["function"] = fn
                tc.setdefault("type", "function")
                if not tc.get("id"):
                    tc["id"] = f"call_{len(out)}_{j}"
                last_tool_call_id = str(tc["id"])
                new_calls.append(tc)
            m["tool_calls"] = new_calls
        if m.get("role") == "tool" and not m.get("tool_call_id") and last_tool_call_id:
            m["tool_call_id"] = last_tool_call_id
        out.append(m)
    return out


# A tool call in Llama's native pythonic format: `NAME{...json...}`, optionally
# wrapped as `<function=NAME{...}>`. Some Llama models (notably
# llama-3.3-70b-versatile on Groq) emit this as plain text instead of a proper
# `tool_calls` field; the provider then returns HTTP 400 (`tool_use_failed`, or a
# validation error reporting the whole `NAME{...}` blob as an unknown tool name).
_NATIVE_TOOL_CALL_RE = re.compile(r"(?:<function=)?([A-Za-z_][A-Za-z0-9_]*)\s*\{")

# Model-kind classification from an OpenAI-compatible /models entry's
# `metadata.tags` (DeepInfra provides these; others may not).
_EMBED_TAGS = {"embed", "embedding", "embeddings", "text-embedding"}
_LLM_TAGS = {"chat", "text-generation", "text", "completion", "instruct"}


def _classify_model_kind(tags: object) -> str:
    """Map a model's tags to 'embedding' | 'llm' | 'unknown'. Anything without
    a recognisable tag (or with none) is 'unknown' — the UI shows those in both
    pickers only as a fallback when no classified model of that kind exists."""
    if not isinstance(tags, (list, tuple)):
        return "unknown"
    tl = {str(t).lower() for t in tags}
    if tl & _EMBED_TAGS:
        return "embedding"
    if tl & _LLM_TAGS:
        return "llm"
    return "unknown"


def _recover_native_tool_call(
    text: str, valid_tools: set[str]
) -> LLMToolCall | None:
    """Recover a tool call from a malformed `NAME{...json...}` text blob.

    Returns the call only when ``NAME`` is one of ``valid_tools`` and the braces
    parse as a JSON object — otherwise ``None`` (never fabricates a call).
    """
    m = _NATIVE_TOOL_CALL_RE.search(text)
    if not m or m.group(1) not in valid_tools:
        return None
    brace_idx = m.end() - 1  # position of the opening '{'
    try:
        # raw_decode stops at the JSON object's own closing brace, so trailing
        # noise (`></function>`, `' which was not...`) and braces inside string
        # values are handled correctly.
        args, _ = json.JSONDecoder().raw_decode(text, brace_idx)
    except ValueError:
        return None
    if not isinstance(args, dict):
        return None
    return LLMToolCall(tool=m.group(1), arguments=args)


def _recover_tool_call_from_error(
    response: httpx.Response, tools: list[dict[str, object]] | None
) -> LLMToolCall | None:
    """If a 400 is a Llama native-format tool-call failure, recover the call."""
    if response.status_code != 400 or not tools:
        return None
    valid = {
        name
        for t in tools
        if isinstance((fn := t.get("function")), dict)
        and isinstance((name := fn.get("name")), str)
    }
    if not valid:
        return None
    try:
        err = (response.json() or {}).get("error") or {}
    except ValueError:
        return None
    # Variant 1: the raw generation is echoed back in `failed_generation`.
    # Variant 2: the validation message embeds the mis-parsed `NAME{...}` blob.
    for field in ("failed_generation", "message"):
        value = err.get(field)
        if isinstance(value, str):
            recovered = _recover_native_tool_call(value, valid)
            if recovered is not None:
                return recovered
    return None


class OpenAILLMAdapter:
    """LLMProvider for the OpenAI Chat Completions API and compatible
    endpoints (Groq, Together, OpenRouter, DeepSeek, ...).

    Registered for both `openai` and `openai_compat`; the two differ only
    in the base_url, which the caller resolves. `transport` is an optional
    httpx transport for testing (MockTransport).
    """

    DEFAULT_TIMEOUT_SECS = 120.0
    MAX_RETRIES = 5  # on HTTP 429 (rate limit), respecting Retry-After
    MAX_RETRY_WAIT_SECS = 60.0

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
        api_key: str | None,
        model_id: str,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None,
        temperature: float,
        top_p: float,
        max_tokens: int,
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": model_id,
            "messages": _normalize_messages_for_openai(messages),
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
        }
        if tools is not None:
            body["tools"] = tools

        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(
                    base_url=base_url,
                    timeout=self._timeout,
                    transport=self._transport,
                ) as client:
                    r = await client.post(
                        "/chat/completions", json=body, headers=headers
                    )
            except httpx.TimeoutException as exc:
                raise LLMTimeoutError(
                    f"OpenAI /chat/completions timed out after {self._timeout}s "
                    f"(model={model_id!r})"
                ) from exc
            except httpx.HTTPError as exc:
                raise LLMError(
                    f"OpenAI /chat/completions transport failed "
                    f"(model={model_id!r}): {exc}"
                ) from exc

            # Rate limited: wait (honouring Retry-After) and retry, so the eval
            # paces itself to the provider's token/req limits instead of failing.
            if r.status_code == 429 and attempt < self.MAX_RETRIES:
                retry_after = _parse_retry_after(r.headers.get("retry-after"))
                wait = retry_after if retry_after is not None else 2.0 ** attempt
                wait = min(wait, self.MAX_RETRY_WAIT_SECS)
                _log.warning(
                    "OpenAI 429 rate-limited (model=%s); attempt %d/%d, waiting %.1fs",
                    model_id, attempt + 1, self.MAX_RETRIES, wait,
                )
                await asyncio.sleep(wait)
                continue
            break

        if r.status_code != 200:
            # Llama models sometimes emit tool calls in their native text format,
            # which strict endpoints reject with 400. Recover the intended call
            # locally instead of failing the whole agentic step (saves a retry —
            # and the tokens it would cost).
            recovered = _recover_tool_call_from_error(r, tools)
            if recovered is not None:
                _log.warning(
                    "Recovered a malformed native-format tool call from HTTP %d "
                    "(model=%s, tool=%s)",
                    r.status_code, model_id, recovered.tool,
                )
                return recovered
            raise LLMError(
                f"OpenAI /chat/completions returned HTTP {r.status_code}: {r.text[:500]}"
            )

        try:
            payload = r.json()
        except json.JSONDecodeError as exc:
            raise LLMError(
                f"OpenAI /chat/completions returned non-JSON body: {r.text[:200]}"
            ) from exc

        choices = payload.get("choices")
        if not choices:
            raise LLMError(
                f"OpenAI /chat/completions returned no choices; got keys {list(payload)}"
            )
        message = choices[0].get("message") or {}

        _usage_raw = payload.get("usage") or {}
        usage = TokenUsage(
            prompt_tokens=int(_usage_raw.get("prompt_tokens", 0)),
            completion_tokens=int(_usage_raw.get("completion_tokens", 0)),
        )

        tool_calls = message.get("tool_calls")
        if tool_calls:
            fn = tool_calls[0].get("function") or {}
            name = fn.get("name")
            if not isinstance(name, str):
                raise LLMError(f"OpenAI tool_call missing string `name`: {tool_calls[0]!r}")
            raw_args = fn.get("arguments", "{}")
            if isinstance(raw_args, str):
                if not raw_args.strip():
                    raise LLMError(
                        f"OpenAI tool_call arguments were empty (model={model_id!r}); "
                        f"a tool call with no arguments is malformed."
                    )
                try:
                    arguments: dict[str, Any] = json.loads(raw_args)
                except json.JSONDecodeError as exc:
                    raise LLMError(
                        f"OpenAI tool_call arguments were a string but not valid "
                        f"JSON: {raw_args!r}"
                    ) from exc
            elif isinstance(raw_args, dict):
                arguments = raw_args
            else:
                raise LLMError(
                    f"OpenAI tool_call arguments had unexpected type "
                    f"{type(raw_args).__name__}: {raw_args!r}"
                )
            return LLMToolCall(tool=name, arguments=arguments, usage=usage)

        content = message.get("content")
        if not isinstance(content, str):
            raise LLMError(
                f"OpenAI message had no tool_calls and no string content: {message!r}"
            )
        return LLMTextResponse(text=content, usage=usage)

    async def list_models(
        self,
        *,
        base_url: str,
        api_key: str | None,
    ) -> list[dict[str, object]]:
        """Return available models from an OpenAI-compatible /models endpoint.

        Each model is classified as embedding / llm / unknown from its
        ``metadata.tags`` when the endpoint provides them (e.g. DeepInfra tags
        embedding models ``embed`` and chat models ``chat``); endpoints that
        expose no tags yield ``unknown`` (the UI then shows them in both
        pickers as a fallback). Raises LLMError on upstream failures.
        """
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=10.0,
                transport=self._transport,
            ) as client:
                r = await client.get("/models", headers=headers)
        except httpx.HTTPError as exc:
            raise LLMError(
                f"OpenAI /models transport failed: {exc}"
            ) from exc

        if r.status_code != 200:
            raise LLMError(
                f"OpenAI /models returned HTTP {r.status_code}: {r.text[:500]}"
            )

        try:
            data = r.json()
        except json.JSONDecodeError as exc:
            raise LLMError(
                f"OpenAI /models returned non-JSON body: {r.text[:200]}"
            ) from exc

        return [
            {"id": entry.get("id", ""),
             "kind": _classify_model_kind((entry.get("metadata") or {}).get("tags"))}
            for entry in data.get("data", [])
            if entry.get("id")
        ]
