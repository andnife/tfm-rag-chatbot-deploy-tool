import pytest

from tfm_rag.domain.errors.chat import UnsupportedProviderError
from tfm_rag.infrastructure.llm_providers.dispatcher import LLMDispatcher
from tfm_rag.infrastructure.llm_providers.ollama import OllamaLLMAdapter


def test_for_provider_returns_registered_adapter() -> None:
    ollama = OllamaLLMAdapter()
    disp = LLMDispatcher({"ollama": ollama})
    assert disp.for_provider("ollama") is ollama


def test_for_provider_raises_for_unknown() -> None:
    disp = LLMDispatcher({"ollama": OllamaLLMAdapter()})
    with pytest.raises(UnsupportedProviderError):
        disp.for_provider("openai")


def test_default_registers_ollama_only() -> None:
    disp = LLMDispatcher.default()
    assert disp.for_provider("ollama") is not None
    with pytest.raises(UnsupportedProviderError):
        disp.for_provider("openai")
