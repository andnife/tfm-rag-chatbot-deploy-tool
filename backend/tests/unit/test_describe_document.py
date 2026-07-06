import pytest

from tfm_rag.application.knowledge.describe_document import describe_document
from tfm_rag.domain.ports.chunker import Chunk
from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMTextResponse,
    LLMToolCall,
)


class _FakeLLM:
    def __init__(self, *responses: object) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def generate(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("generate called more times than expected")
        return self._responses.pop(0)


class _BoomLLM:
    async def generate(self, **kwargs: object) -> object:
        raise RuntimeError("provider down")


def _chunks(n: int) -> list[Chunk]:
    return [Chunk(index=i, text=f"chunk-{i} body", metadata={}) for i in range(n)]


@pytest.mark.asyncio
async def test_single_call_returns_text() -> None:
    llm = _FakeLLM(LLMTextResponse(text="This document is about cats."))
    out = await describe_document(
        _chunks(3), llm=llm, base_url="http://x", api_key=None, model_id="m",
    )
    assert out == "This document is about cats."
    assert len(llm.calls) == 1
    # tools must be None (free-text generation, no tool-calling)
    assert llm.calls[0]["tools"] is None


@pytest.mark.asyncio
async def test_empty_chunks_returns_none_without_calling_llm() -> None:
    llm = _FakeLLM()
    out = await describe_document(
        [], llm=llm, base_url="http://x", api_key=None, model_id="m",
    )
    assert out is None
    assert llm.calls == []


@pytest.mark.asyncio
async def test_llm_error_returns_none() -> None:
    out = await describe_document(
        _chunks(2), llm=_BoomLLM(), base_url="http://x", api_key=None, model_id="m",
    )
    assert out is None


@pytest.mark.asyncio
async def test_output_truncated_to_80_words() -> None:
    long_text = " ".join(["word"] * 200)
    llm = _FakeLLM(LLMTextResponse(text=long_text))
    out = await describe_document(
        _chunks(1), llm=llm, base_url="http://x", api_key=None, model_id="m",
    )
    assert out is not None
    assert len(out.split()) == 80


@pytest.mark.asyncio
async def test_samples_first_and_spread_chunks_for_large_doc() -> None:
    llm = _FakeLLM(LLMTextResponse(text="summary"))
    await describe_document(
        _chunks(100), llm=llm, base_url="http://x", api_key=None, model_id="m",
    )
    user_msg = llm.calls[0]["messages"][-1]["content"]
    # first and last chunk always sampled; exactly 5 chunks referenced (not all 100)
    assert "chunk-0 body" in user_msg
    assert "chunk-99 body" in user_msg
    assert user_msg.count(" body") == 5  # only the sampled subset, not every chunk


@pytest.mark.asyncio
async def test_tool_call_response_returns_none() -> None:
    llm = _FakeLLM(LLMToolCall(tool="whatever", arguments={}))
    out = await describe_document(
        _chunks(1), llm=llm, base_url="http://x", api_key=None, model_id="m",
    )
    assert out is None
