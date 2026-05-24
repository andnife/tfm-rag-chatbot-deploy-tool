import pytest

from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMTextResponse,
    LLMToolCall,
    RetrievalIteration,
)


def test_retrieval_iteration_round_trip() -> None:
    it = RetrievalIteration(
        index=0,
        tool="search_docs",
        query="what is X",
        num_chunks=3,
        latency_ms=482.0,
    )
    data = it.to_dict()
    assert data == {
        "index": 0,
        "tool": "search_docs",
        "query": "what is X",
        "num_chunks": 3,
        "latency_ms": 482.0,
    }
    assert RetrievalIteration.from_dict(data) == it


def test_retrieval_iteration_accepts_terminal_tool_without_query() -> None:
    it = RetrievalIteration(
        index=1,
        tool="final_answer",
        query=None,
        num_chunks=None,
        latency_ms=120.5,
    )
    data = it.to_dict()
    assert data["query"] is None
    assert data["num_chunks"] is None


def test_retrieval_iteration_negative_index_rejected() -> None:
    from tfm_rag.domain.errors.common import ValidationError

    with pytest.raises(ValidationError):
        RetrievalIteration(
            index=-1, tool="search_docs", query="x",
            num_chunks=0, latency_ms=0.0,
        )


def test_llm_tool_call_attribute_access() -> None:
    call = LLMToolCall(tool="search_docs", arguments={"query": "hi"})
    assert call.tool == "search_docs"
    assert call.arguments == {"query": "hi"}


def test_llm_text_response_attribute_access() -> None:
    resp = LLMTextResponse(text="hello world")
    assert resp.text == "hello world"
