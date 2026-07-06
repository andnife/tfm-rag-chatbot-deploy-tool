from tfm_rag.domain.errors.chat import UnsupportedProviderError
from tfm_rag.domain.ports.llm import LLMProvider
from tfm_rag.infrastructure.llm_providers.ollama import OllamaLLMAdapter
from tfm_rag.infrastructure.llm_providers.openai import OpenAILLMAdapter


class LLMDispatcher:
    """Routes (`provider_id` → `LLMProvider`).

    Symmetric to `EmbedderDispatcher`. Registers `ollama`, `openai`, and
    `openai_compat` (the latter two share one OpenAILLMAdapter instance,
    differing only by resolved base_url).
    """

    def __init__(self, registry: dict[str, LLMProvider]) -> None:
        self._registry = registry

    def for_provider(self, provider_id: str) -> LLMProvider:
        adapter = self._registry.get(provider_id)
        if adapter is None:
            raise UnsupportedProviderError(
                f"No LLMProvider registered for provider_id={provider_id!r}. "
                f"Available: {sorted(self._registry)}"
            )
        return adapter

    @classmethod
    def default(cls) -> "LLMDispatcher":
        openai = OpenAILLMAdapter()
        return cls(
            {
                "ollama": OllamaLLMAdapter(),
                "openai": openai,
                "openai_compat": openai,
            }
        )
