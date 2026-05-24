from tfm_rag.domain.errors.chat import UnsupportedProviderError
from tfm_rag.domain.ports.llm import LLMProvider
from tfm_rag.infrastructure.llm_providers.ollama import OllamaLLMAdapter


class LLMDispatcher:
    """Routes (`provider_id` → `LLMProvider`).

    Symmetric to `EmbedderDispatcher`. Plan #15 wires only `ollama`;
    `openai` and `openai_compat` adapters land in follow-up plans.
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
        return cls({"ollama": OllamaLLMAdapter()})
