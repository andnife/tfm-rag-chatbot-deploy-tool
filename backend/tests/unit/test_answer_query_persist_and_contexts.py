from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tfm_rag.application.chat.answer_query import answer_query


def _no_sources_repo_factory(_session: Any) -> Any:
    """Stub sources repo that always returns an empty list (no DB sources)."""
    repo = MagicMock()
    repo.list_by_kb = AsyncMock(return_value=[])
    return repo
from tfm_rag.domain.catalog.agent_tools import (
    TOOL_FINAL_ANSWER,
    TOOL_SEARCH_DOCS,
)
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.domain.value_objects.retrieval_iteration import LLMToolCall
from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk
from tfm_rag.infrastructure.persistence.repository import RequestContext


def _ctx() -> RequestContext:
    return RequestContext(tenant_id=uuid4(), user_id=uuid4())


def _chunk(text: str, idx: int = 0) -> RetrievedChunk:
    return RetrievedChunk(
        point_id=f"pid-{idx}",
        content=text,
        source_id=uuid4(),
        source_filename="manual.pdf",
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
    row.system_prompt = "be terse"
    row.llm_selection = {
        "provider_id": "ollama",
        "credential_id": str(uuid4()),
        "model_id": "llama3.1",
    }
    row.pipeline_config = PipelineConfig.default().to_dict()
    row.widget_config = {}
    return row


def _chatbot_repo(row) -> MagicMock:
    repo = MagicMock()
    repo.get = AsyncMock(return_value=row)
    repo.list_kb_ids = AsyncMock(return_value=[uuid4()])
    return repo


def _fake_settings() -> MagicMock:
    s = MagicMock()
    s.ollama_base_url = "http://ollama:11434"
    return s


class _ScriptedLLM:
    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._script.pop(0)


@pytest.mark.asyncio
async def test_retrieved_contexts_populated_from_search_results() -> None:
    """AnswerView.retrieved_contexts contains the content of every chunk
    seen across the loop (in seen_chunks insertion order).
    """
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = _chatbot_repo(row)

    llm = _ScriptedLLM([
        LLMToolCall(tool=TOOL_SEARCH_DOCS, arguments={"query": "q"}),
        LLMToolCall(tool=TOOL_FINAL_ANSWER, arguments={"answer": "ok"}),
    ])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=llm)

    chunks = [_chunk("alpha", 0), _chunk("beta", 1)]

    async def fake_retrieve(*args: Any, **kwargs: Any) -> Any:
        return chunks

    async def fake_create(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_append(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_touch(*args: Any, **kwargs: Any) -> None:
        return None

    view = await answer_query(
        MagicMock(), ctx,
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
    assert view.retrieved_contexts == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_retrieved_contexts_dedup_by_point_id() -> None:
    """If two search calls return overlapping chunks, retrieved_contexts
    contains each chunk's content only once (dedup mirrors citations).
    """
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = _chatbot_repo(row)

    shared = _chunk("shared", 0)
    llm = _ScriptedLLM([
        LLMToolCall(tool=TOOL_SEARCH_DOCS, arguments={"query": "q1"}),
        LLMToolCall(tool=TOOL_SEARCH_DOCS, arguments={"query": "q2"}),
        LLMToolCall(tool=TOOL_FINAL_ANSWER, arguments={"answer": "ok"}),
    ])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=llm)

    results = [[shared], [shared]]

    async def fake_retrieve(*args: Any, **kwargs: Any) -> Any:
        return results.pop(0)

    async def fake_pass(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_void(*args: Any, **kwargs: Any) -> None:
        return None

    view = await answer_query(
        MagicMock(), ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: MagicMock(),
        sources_repo_factory=_no_sources_repo_factory,
        llm_dispatcher=dispatcher,
        retrieve_docs=fake_retrieve,
        create_session=fake_pass,
        append_message=fake_pass,
        touch_session=fake_void,
        qdrant=MagicMock(),
        embedder_dispatcher=MagicMock(),
        settings=_fake_settings(),
        chatbot_id=row.id,
        session_id=None,
        user_message="?",
    )
    assert view.retrieved_contexts == ["shared"]


@pytest.mark.asyncio
async def test_persist_false_skips_session_and_message_persistence() -> None:
    """When persist=False, create_session / append_message / touch_session
    must NOT be called. The AnswerView still has a (throwaway) session_id
    and message_id so callers don't need to deal with Optional types.
    """
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = _chatbot_repo(row)

    llm = _ScriptedLLM([
        LLMToolCall(tool=TOOL_FINAL_ANSWER, arguments={"answer": "ok"}),
    ])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=llm)

    create_calls = 0
    append_calls = 0
    touch_calls = 0

    async def fake_create(*args: Any, **kwargs: Any) -> Any:
        nonlocal create_calls
        create_calls += 1
        return uuid4()

    async def fake_append(*args: Any, **kwargs: Any) -> Any:
        nonlocal append_calls
        append_calls += 1
        return uuid4()

    async def fake_touch(*args: Any, **kwargs: Any) -> None:
        nonlocal touch_calls
        touch_calls += 1

    view = await answer_query(
        MagicMock(), ctx,
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
        persist=False,
    )
    assert create_calls == 0
    assert append_calls == 0
    assert touch_calls == 0
    assert view.content == "ok"
    # Throwaway UUIDs are still returned (so AnswerView's types stay clean).
    assert view.session_id is not None
    assert view.message_id is not None


@pytest.mark.asyncio
async def test_persist_true_default_still_persists() -> None:
    """Regression guard: default behaviour (persist=True) must remain the
    same as plan #15 — create_session called when no session_id, then
    two append_message + one touch.
    """
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = _chatbot_repo(row)

    llm = _ScriptedLLM([
        LLMToolCall(tool=TOOL_FINAL_ANSWER, arguments={"answer": "ok"}),
    ])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=llm)

    create_calls = 0
    append_calls = 0
    touch_calls = 0

    async def fake_create(*args: Any, **kwargs: Any) -> Any:
        nonlocal create_calls
        create_calls += 1
        return uuid4()

    async def fake_append(*args: Any, **kwargs: Any) -> Any:
        nonlocal append_calls
        append_calls += 1
        return uuid4()

    async def fake_touch(*args: Any, **kwargs: Any) -> None:
        nonlocal touch_calls
        touch_calls += 1

    await answer_query(
        MagicMock(), ctx,
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
    assert create_calls == 1
    assert append_calls == 2  # user + assistant
    assert touch_calls == 1
