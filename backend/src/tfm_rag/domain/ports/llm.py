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

    async def list_models(
        self,
        *,
        base_url: str,
        api_key: str | None,
    ) -> list[dict[str, object]]:
        """Return available models from the provider endpoint.

        Each entry is ``{"id": str, "kind": "llm" | "embedding" | "unknown"}``.

        Upstream-failure contract: RAISES on any upstream failure — non-200
        HTTP status, network error, or JSON parse error. The caller (typically
        the ``list_credential_models`` use-case) is responsible for catching
        these and converting to ``{"models": [], "error": <message>}``.

        Parameters
        ----------
        base_url:
            Provider endpoint base URL (e.g. ``http://localhost:11434`` for
            Ollama, ``https://api.openai.com/v1`` for OpenAI-compatible).
        api_key:
            Bearer token for authenticated providers; ``None`` for keyless
            providers (Ollama).
        """
        ...


class LLMDispatcherPort(Protocol):
    """Resolves a `provider_id` to the matching `LLMProvider` adapter.

    Lets use cases pick an LLM at runtime (the provider is derived from the
    credential) without depending on the concrete infrastructure dispatcher.
    Raises `UnsupportedProviderError` for unknown providers.
    """

    def for_provider(self, provider_id: str) -> LLMProvider: ...
