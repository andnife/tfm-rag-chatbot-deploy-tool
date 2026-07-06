import pytest

from tfm_rag.domain.errors.chat import UnsupportedProviderError
from tfm_rag.infrastructure.embedders.dispatcher import EmbedderDispatcher
from tfm_rag.infrastructure.embedders.ollama import OllamaEmbedder


def test_dispatcher_returns_ollama_for_ollama_provider() -> None:
    d = EmbedderDispatcher.default()
    emb = d.for_provider("ollama")
    assert isinstance(emb, OllamaEmbedder)


def test_dispatcher_raises_for_unknown_provider() -> None:
    d = EmbedderDispatcher.default()
    with pytest.raises(UnsupportedProviderError, match="unknown_provider"):
        d.for_provider("unknown_provider")


def test_dispatcher_accepts_custom_registry() -> None:
    sentinel = OllamaEmbedder()
    d = EmbedderDispatcher({"custom": sentinel})
    assert d.for_provider("custom") is sentinel
    with pytest.raises(UnsupportedProviderError):
        d.for_provider("ollama")
