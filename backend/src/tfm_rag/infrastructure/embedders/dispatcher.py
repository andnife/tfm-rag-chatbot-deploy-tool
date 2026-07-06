from tfm_rag.domain.errors.chat import UnsupportedProviderError
from tfm_rag.domain.ports.embedder import Embedder
from tfm_rag.infrastructure.embedders.ollama import OllamaEmbedder
from tfm_rag.infrastructure.embedders.openai import OpenAIEmbedder


class EmbedderDispatcher:
    """Routes (`provider_id` → `Embedder`).

    Registers `ollama` and `openai_compat`.
    """

    def __init__(self, registry: dict[str, Embedder]) -> None:
        self._registry = registry

    def for_provider(self, provider_id: str) -> Embedder:
        emb = self._registry.get(provider_id)
        if emb is None:
            raise UnsupportedProviderError(
                f"No Embedder registered for provider_id={provider_id!r}. "
                f"Available: {sorted(self._registry)}"
            )
        return emb

    @classmethod
    def default(cls) -> "EmbedderDispatcher":
        return cls({"ollama": OllamaEmbedder(), "openai_compat": OpenAIEmbedder()})
