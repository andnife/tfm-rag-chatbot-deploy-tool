import inspect

from tfm_rag.application.chat import retrieve_docs as rd_module


def test_retrieve_docs_imports_resolve_inference_target() -> None:
    # The use case must delegate endpoint resolution to resolve_inference_target
    # (derives provider from credential) rather than reading selection.provider_id.
    src = inspect.getsource(rd_module)
    assert "resolve_inference_target(" in src
    assert "base_url = settings.ollama_base_url" not in src
    assert "selection.provider_id" not in src
