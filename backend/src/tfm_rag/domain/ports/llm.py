from typing import Protocol

from tfm_rag.domain.value_objects.retrieval_iteration import LLMResponse


class LLMProvider(Protocol):
    """Generates the next assistant turn given a conversation and a set of
    tools.

    `messages` follows the OpenAI Chat Completions shape:
        [
          {"role": "system", "content": "..."},
          {"role": "user", "content": "..."},
          {"role": "assistant", "tool_calls": [{"function": {...}}]},
          {"role": "tool", "tool_call_id": "...", "name": "...", "content": "..."},
          ...
        ]

    `tools` is the JSON-Schema list returned by
    `domain.catalog.agent_tools.build_tool_schemas()`. When `None`, the
    LLM is free to reply with plain text (returned as `LLMTextResponse`).

    `base_url` / `api_key` follow the same convention as
    `Embedder.embed` — SERVER_ENV providers (Ollama) get the value from
    Settings; TENANT_CREDENTIAL providers get a decrypted key.

    Adapters MUST translate provider-specific tool-call JSON into the
    domain VOs `LLMToolCall(tool, arguments)` or `LLMTextResponse(text)`.
    """

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
    ) -> LLMResponse: ...
