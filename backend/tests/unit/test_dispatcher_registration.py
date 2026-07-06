from tfm_rag.infrastructure.embedders.dispatcher import EmbedderDispatcher
from tfm_rag.infrastructure.embedders.openai import OpenAIEmbedder
from tfm_rag.infrastructure.llm_providers.dispatcher import LLMDispatcher
from tfm_rag.infrastructure.llm_providers.openai import OpenAILLMAdapter


def test_llm_dispatcher_registers_openai_and_compat_with_shared_instance() -> None:
    d = LLMDispatcher.default()
    openai = d.for_provider("openai")
    compat = d.for_provider("openai_compat")
    assert isinstance(openai, OpenAILLMAdapter)
    assert openai is compat  # same instance
    assert d.for_provider("ollama") is not None


def test_embedder_dispatcher_registers_openai_compat() -> None:
    d = EmbedderDispatcher.default()
    assert isinstance(d.for_provider("openai_compat"), OpenAIEmbedder)
    assert d.for_provider("ollama") is not None
