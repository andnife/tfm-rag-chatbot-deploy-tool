from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tfm_rag.application.chat.answer_query import AnswerView, answer_query
from tfm_rag.domain.catalog.agent_tools import (
    TOOL_ABSTAIN,
    TOOL_FINAL_ANSWER,
    TOOL_SEARCH_DOCS,
)
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMTextResponse,
    LLMToolCall,
)
from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk
from tfm_rag.infrastructure.persistence.repository import RequestContext


def _no_sources_repo_factory(_session: Any) -> Any:
    """Stub sources repo that always returns an empty list (no DB sources)."""
    repo = MagicMock()
    repo.list_by_kb = AsyncMock(return_value=[])
    return repo


def _ctx() -> RequestContext:
    return RequestContext(tenant_id=uuid4(), user_id=uuid4())


def _chunk(text: str, source: str = "manual.pdf", idx: int = 0) -> RetrievedChunk:
    return RetrievedChunk(
        point_id=f"pid-{text}-{idx}",
        content=text,
        source_id=uuid4(),
        source_filename=source,
        chunk_index=idx,
        score=0.9,
        metadata={},
    )


def _chatbot_row(tenant_id) -> MagicMock:
    row = MagicMock()
    row.id = uuid4()
    row.tenant_id = tenant_id
    row.name = "Bot"
    row.description = None
    row.system_prompt = "You are a helpful assistant."
    row.llm_selection = {
        "provider_id": "ollama",
        "credential_id": str(uuid4()),
        "model_id": "llama3.1",
    }
    row.pipeline_config = PipelineConfig.default().to_dict()
    row.widget_config = {}
    return row


def _chatbot_repo(row: MagicMock) -> MagicMock:
    repo = MagicMock()
    repo.get = AsyncMock(return_value=row)
    repo.list_kb_ids = AsyncMock(return_value=[uuid4()])
    return repo


def _fake_settings() -> MagicMock:
    s = MagicMock()
    s.ollama_base_url = "http://ollama:11434"
    return s


class _ScriptedLLM:
    """LLMProvider fake that returns the next response from a script."""

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._script.pop(0)


@pytest.mark.asyncio
async def test_answer_query_one_iteration_with_search_then_final() -> None:
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = _chatbot_repo(row)

    llm = _ScriptedLLM([
        LLMToolCall(tool=TOOL_SEARCH_DOCS, arguments={"query": "what is X"}),
        LLMToolCall(tool=TOOL_FINAL_ANSWER, arguments={"answer": "X is a thing."}),
    ])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=llm)

    chunks = [_chunk("X is described here.")]
    retrieve = AsyncMock(return_value=chunks)

    captured_msgs: list[dict[str, Any]] = []

    async def fake_create_session(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_append_message(*args: Any, **kwargs: Any) -> Any:
        captured_msgs.append(kwargs)
        return uuid4()

    async def fake_touch(*args: Any, **kwargs: Any) -> None:
        return None

    db = MagicMock()
    view = await answer_query(
        db, ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: MagicMock(),
        sources_repo_factory=_no_sources_repo_factory,
        llm_dispatcher=dispatcher,
        retrieve_docs=retrieve,
        create_session=fake_create_session,
        append_message=fake_append_message,
        touch_session=fake_touch,
        qdrant=MagicMock(),
        embedder_dispatcher=MagicMock(),
        settings=_fake_settings(),
        chatbot_id=row.id,
        session_id=None,
        user_message="what is X?",
    )

    assert isinstance(view, AnswerView)
    assert view.content == "X is a thing."
    assert len(view.iterations) == 2
    assert view.iterations[0].tool == TOOL_SEARCH_DOCS
    assert view.iterations[0].num_chunks == 1
    assert view.iterations[1].tool == TOOL_FINAL_ANSWER
    assert len(view.citations) == 1
    assert view.citations[0].source_name == "manual.pdf"

    assert len(captured_msgs) == 2
    assert captured_msgs[0]["role"] == "user"
    assert captured_msgs[0]["content"] == "what is X?"
    assert captured_msgs[1]["role"] == "assistant"
    assert captured_msgs[1]["content"] == "X is a thing."
    persisted = captured_msgs[1]
    assert isinstance(persisted["citations"], list)
    assert persisted["citations"][0]["source_name"] == "manual.pdf"
    assert "iterations" in persisted["metadata"]
    assert len(persisted["metadata"]["iterations"]) == 2

    retrieve.assert_awaited_once()
    rcall = retrieve.await_args
    assert rcall.kwargs["query"] == "what is X"


@pytest.mark.asyncio
async def test_answer_query_abstain_branch() -> None:
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = _chatbot_repo(row)

    llm = _ScriptedLLM([
        LLMToolCall(tool=TOOL_ABSTAIN, arguments={"reason": "no docs match"}),
    ])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=llm)

    appended: list[dict[str, Any]] = []

    async def fake_append(*args: Any, **kwargs: Any) -> Any:
        appended.append(kwargs)
        return uuid4()

    async def fake_create(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_touch(*args: Any, **kwargs: Any) -> None:
        return None

    db = MagicMock()
    view = await answer_query(
        db, ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: MagicMock(),
        sources_repo_factory=_no_sources_repo_factory,
        llm_dispatcher=dispatcher,
        retrieve_docs=AsyncMock(return_value=[]),
        create_session=fake_create,
        append_message=fake_append,
        touch_session=fake_touch,
        qdrant=MagicMock(),
        embedder_dispatcher=MagicMock(),
        settings=_fake_settings(),
        chatbot_id=row.id,
        session_id=None,
        user_message="something obscure",
    )

    assert "no docs match" in view.content.lower()
    assert view.citations == []
    assert view.iterations[-1].tool == TOOL_ABSTAIN

    assistant_msg = appended[-1]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["citations"] == []


@pytest.mark.asyncio
async def test_answer_query_max_iterations_synthesises_abstain() -> None:
    """If the LLM never emits a terminal tool, we cap at
    max_retrieval_iterations and synthesise an abstain message rather
    than looping forever.
    """
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    pipe = PipelineConfig.from_dict(row.pipeline_config)
    pipe = PipelineConfig(
        top_k=pipe.top_k,
        score_threshold=pipe.score_threshold,
        agentic_mode=True,
        max_retrieval_iterations=2,
        enable_reranker=False,
        reranker_initial_top_k=30,
        abstain_when_insufficient=True,
        router_llm_selection=None,
        generation=pipe.generation,
    )
    row.pipeline_config = pipe.to_dict()
    chatbot_repo = _chatbot_repo(row)

    llm = _ScriptedLLM([
        LLMToolCall(tool=TOOL_SEARCH_DOCS, arguments={"query": "q1"}),
        LLMToolCall(tool=TOOL_SEARCH_DOCS, arguments={"query": "q2"}),
    ])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=llm)

    async def fake_append(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_create(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_touch(*args: Any, **kwargs: Any) -> None:
        return None

    db = MagicMock()
    view = await answer_query(
        db, ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: MagicMock(),
        sources_repo_factory=_no_sources_repo_factory,
        llm_dispatcher=dispatcher,
        retrieve_docs=AsyncMock(return_value=[_chunk("noise")]),
        create_session=fake_create,
        append_message=fake_append,
        touch_session=fake_touch,
        qdrant=MagicMock(),
        embedder_dispatcher=MagicMock(),
        settings=_fake_settings(),
        chatbot_id=row.id,
        session_id=None,
        user_message="?",
    )

    assert len(llm.calls) == 2
    assert view.iterations[-1].tool == TOOL_ABSTAIN
    assert "max iterations" in view.content.lower()


@pytest.mark.asyncio
async def test_answer_query_text_response_treated_as_final() -> None:
    """If the LLM ignores the tool schema and returns raw text, we treat
    that as an implicit final_answer rather than crashing.
    """
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = _chatbot_repo(row)

    llm = _ScriptedLLM([LLMTextResponse(text="here is your answer")])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=llm)

    async def fake_append(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_create(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_touch(*args: Any, **kwargs: Any) -> None:
        return None

    db = MagicMock()
    view = await answer_query(
        db, ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: MagicMock(),
        sources_repo_factory=_no_sources_repo_factory,
        llm_dispatcher=dispatcher,
        retrieve_docs=AsyncMock(return_value=[]),
        create_session=fake_create,
        append_message=fake_append,
        touch_session=fake_touch,
        qdrant=MagicMock(),
        embedder_dispatcher=MagicMock(),
        settings=_fake_settings(),
        chatbot_id=row.id,
        session_id=None,
        user_message="x",
    )

    assert view.content == "here is your answer"
    assert view.iterations[-1].tool == TOOL_FINAL_ANSWER
    assert view.citations == []


@pytest.mark.asyncio
async def test_answer_query_raises_when_chatbot_missing() -> None:
    ctx = _ctx()
    chatbot_repo = MagicMock()
    chatbot_repo.get = AsyncMock(side_effect=NotFoundError("nope"))
    chatbot_repo.list_kb_ids = AsyncMock(return_value=[])

    async def fake_unused(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("should not be called")

    db = MagicMock()
    with pytest.raises(ChatbotNotFoundError):
        await answer_query(
            db, ctx,
            chatbot_repo_factory=lambda s, c: chatbot_repo,
            kb_repo_factory=lambda s, c: MagicMock(),
            llm_dispatcher=MagicMock(),
            retrieve_docs=fake_unused,
            create_session=fake_unused,
            append_message=fake_unused,
            touch_session=fake_unused,
            qdrant=MagicMock(),
            embedder_dispatcher=MagicMock(),
            settings=_fake_settings(),
            chatbot_id=uuid4(),
            session_id=None,
            user_message="x",
        )


@pytest.mark.asyncio
async def test_answer_query_reuses_existing_session_when_id_passed() -> None:
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = _chatbot_repo(row)

    llm = _ScriptedLLM([
        LLMToolCall(tool=TOOL_FINAL_ANSWER, arguments={"answer": "ok"}),
    ])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=llm)

    existing_session = uuid4()
    create_calls = 0

    async def fake_create(*args: Any, **kwargs: Any) -> Any:
        nonlocal create_calls
        create_calls += 1
        return uuid4()

    async def fake_append(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_touch(*args: Any, **kwargs: Any) -> None:
        return None

    db = MagicMock()
    view = await answer_query(
        db, ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: MagicMock(),
        sources_repo_factory=_no_sources_repo_factory,
        llm_dispatcher=dispatcher,
        retrieve_docs=AsyncMock(return_value=[]),
        create_session=fake_create,
        append_message=fake_append,
        touch_session=fake_touch,
        qdrant=MagicMock(),
        embedder_dispatcher=MagicMock(),
        settings=_fake_settings(),
        chatbot_id=row.id,
        session_id=existing_session,
        user_message="x",
    )

    assert view.session_id == existing_session
    assert create_calls == 0


@pytest.mark.asyncio
async def test_answer_query_deduplicates_citations_across_iterations() -> None:
    """If two search_docs calls return overlapping chunks (same point_id),
    citations should not be duplicated.
    """
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = _chatbot_repo(row)

    shared = _chunk("repeated", idx=0)

    llm = _ScriptedLLM([
        LLMToolCall(tool=TOOL_SEARCH_DOCS, arguments={"query": "q1"}),
        LLMToolCall(tool=TOOL_SEARCH_DOCS, arguments={"query": "q2"}),
        LLMToolCall(tool=TOOL_FINAL_ANSWER, arguments={"answer": "a"}),
    ])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=llm)

    retrieve_results = [[shared], [shared]]

    async def fake_retrieve(*args: Any, **kwargs: Any) -> Any:
        return retrieve_results.pop(0)

    async def fake_append(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_create(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_touch(*args: Any, **kwargs: Any) -> None:
        return None

    db = MagicMock()
    view = await answer_query(
        db, ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: MagicMock(),
        sources_repo_factory=_no_sources_repo_factory,
        llm_dispatcher=dispatcher,
        retrieve_docs=fake_retrieve,
        create_session=fake_create,
        append_message=fake_append,
        touch_session=fake_touch,
        qdrant=MagicMock(),
        embedder_dispatcher=MagicMock(),
        settings=_fake_settings(),
        chatbot_id=row.id,
        session_id=None,
        user_message="?",
    )

    assert len(view.citations) == 1
    assert view.citations[0].chunk_id == shared.point_id
