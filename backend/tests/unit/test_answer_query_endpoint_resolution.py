import inspect

from tfm_rag.application.chat import answer_query as aq_module


def test_answer_query_imports_resolve_inference_target() -> None:
    # The use case must delegate endpoint resolution to resolve_inference_target
    # (derives provider from credential) rather than reading selection.provider_id
    # or hardcoding settings.ollama_base_url.
    src = inspect.getsource(aq_module)
    assert "resolve_inference_target(" in src
    assert "base_url = settings.ollama_base_url" not in src
    assert "sel.provider_id" not in src
