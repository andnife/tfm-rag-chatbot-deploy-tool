from uuid import uuid4

import pytest

from tfm_rag.application.chat.synthesize import synthesize_answer
from tfm_rag.domain.catalog.routes import ROUTE_DOCS, ROUTE_NORMAL, ROUTE_SQL
from tfm_rag.domain.value_objects.pipeline_config import GenerationConfig
from tfm_rag.domain.value_objects.retrieval_iteration import LLMTextResponse
from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk


class _FakeLLM:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[dict] = []

    async def generate(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return LLMTextResponse(text=self._text)


def _chunk(content: str) -> RetrievedChunk:
    return RetrievedChunk(
        point_id=str(uuid4()), content=content, source_id=uuid4(),
        source_filename="f.txt", chunk_index=0, score=0.9, metadata={},
    )


@pytest.mark.asyncio
async def test_docs_route_returns_answer_and_citations() -> None:
    llm = _FakeLLM("Grounded answer.")
    content, citations = await synthesize_answer(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=GenerationConfig(), route=ROUTE_DOCS,
        system_prompt="be helpful", user_message="q",
        chunks=[_chunk("relevant text")],
    )
    assert content == "Grounded answer."
    assert len(citations) == 1
    # The chunk text reached the model.
    assert "relevant text" in str(llm.calls[0]["messages"])


@pytest.mark.asyncio
async def test_sql_results_instruct_authoritative_answer() -> None:
    """When SQL results are present, the synthesis prompt must tell the model the
    result IS the answer — otherwise the model declines with the value in hand
    ('no tengo suficiente información' despite a COUNT of 10)."""
    llm = _FakeLLM("There are 10.")
    await synthesize_answer(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=GenerationConfig(), route=ROUTE_SQL,
        system_prompt="be helpful", user_message="how many asian countries?",
        chunks=[], sql_contexts=["| COUNT(*) |\n| 10 |"],
    )
    system = llm.calls[0]["messages"][0]["content"].lower()
    assert "authoritative" in system
    assert "is the answer" in system


@pytest.mark.asyncio
async def test_docs_prompt_instructs_no_info_sentinel() -> None:
    """The docs synthesis prompt must instruct the model to emit the exact
    NO_INFO sentinel (not free-form "I don't have that") when the answer isn't
    in the material, so the orchestrator can redirect to unified abstention."""
    from tfm_rag.application.chat.synthesize import NO_INFO_SENTINEL

    llm = _FakeLLM("ans")
    await synthesize_answer(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=GenerationConfig(), route=ROUTE_DOCS,
        system_prompt="be helpful", user_message="q",
        chunks=[_chunk("relevant text")], sql_contexts=None,
    )
    system = llm.calls[0]["messages"][0]["content"]
    assert NO_INFO_SENTINEL in system


@pytest.mark.asyncio
async def test_docs_only_omits_sql_instruction() -> None:
    """A docs-only answer (no SQL results) keeps the document prompt untouched."""
    llm = _FakeLLM("ans")
    await synthesize_answer(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=GenerationConfig(), route=ROUTE_DOCS,
        system_prompt="be helpful", user_message="q",
        chunks=[_chunk("relevant text")], sql_contexts=None,
    )
    system = llm.calls[0]["messages"][0]["content"].lower()
    assert "authoritative" not in system


@pytest.mark.asyncio
async def test_docs_context_does_not_leak_filename_or_index_markers() -> None:
    # The synthesis answer should read as a direct synthesis, not "según el
    # documento [2]". We don't feed the model bracketed indices or file names
    # in the excerpt block, so it has nothing to echo back into the answer.
    llm = _FakeLLM("Grounded answer.")
    await synthesize_answer(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=GenerationConfig(), route=ROUTE_DOCS,
        system_prompt="be helpful", user_message="q",
        chunks=[_chunk("relevant text")],
    )
    msgs = str(llm.calls[0]["messages"])
    assert "relevant text" in msgs  # the excerpt body still reaches the model
    assert "f.txt" not in msgs  # but not the file name
    assert "[0]" not in msgs and "[1]" not in msgs  # nor bracketed indices
    system = next(
        m["content"] for m in llm.calls[0]["messages"] if m["role"] == "system"
    )
    # The model is explicitly told to synthesise without naming sources.
    assert "do not" in system.lower() or "don't" in system.lower()


@pytest.mark.asyncio
async def test_normal_route_has_no_citations_and_ignores_chunks() -> None:
    llm = _FakeLLM("Hi! I can answer questions about your docs.")
    content, citations = await synthesize_answer(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=GenerationConfig(), route=ROUTE_NORMAL,
        system_prompt="be helpful", user_message="hello",
        chunks=[_chunk("should be ignored")],
    )
    assert citations == []
    assert "should be ignored" not in str(llm.calls[0]["messages"])


@pytest.mark.asyncio
async def test_sql_contexts_reach_the_model_without_chunks() -> None:
    from tfm_rag.domain.catalog.routes import ROUTE_SQL

    llm = _FakeLLM("There are 3 users.")
    content, citations = await synthesize_answer(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=GenerationConfig(), route=ROUTE_SQL,
        system_prompt="be helpful", user_message="how many users?",
        chunks=[], sql_contexts=["| count |\n|---|\n| 3 |"],
    )
    assert content == "There are 3 users."
    assert citations == []
    assert "| count |" in str(llm.calls[0]["messages"])


@pytest.mark.asyncio
async def test_both_route_includes_chunks_and_sql() -> None:
    from tfm_rag.domain.catalog.routes import ROUTE_BOTH

    llm = _FakeLLM("Combined answer.")
    content, citations = await synthesize_answer(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=GenerationConfig(), route=ROUTE_BOTH,
        system_prompt="be helpful", user_message="q",
        chunks=[_chunk("doc text")], sql_contexts=["| n |\n|---|\n| 7 |"],
    )
    assert len(citations) == 1  # one per chunk
    msgs = str(llm.calls[0]["messages"])
    assert "doc text" in msgs and "| n |" in msgs
