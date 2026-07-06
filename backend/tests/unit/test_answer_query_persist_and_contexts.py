from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import tfm_rag.application.chat.answer_query as mod
from tfm_rag.application.chat.answer_query import answer_query
from tfm_rag.domain.catalog.evaluator_schemas import (
    GRADE_VERDICT_TOOL,
    ROUTE_DECISION_TOOL,
)
from tfm_rag.domain.catalog.routes import ROUTE_DOCS, ROUTE_NORMAL
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMTextResponse,
    LLMToolCall,
)
from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk
from tfm_rag.domain.value_objects.role_llm_selections import RoleLLMSelections
from tfm_rag.infrastructure.persistence.repository import RequestContext


def _no_sources_repo_factory() -> Any:
    repo = MagicMock()
    repo.list_sources_by_kb = AsyncMock(return_value=[])
    return repo


def _ctx() -> RequestContext:
    return RequestContext(tenant_id=uuid4(), user_id=uuid4())


def _chunk(text: str, idx: int = 0) -> RetrievedChunk:
    return RetrievedChunk(
        point_id=f"pid-{idx}", content=text, source_id=uuid4(),
        source_filename="manual.pdf", chunk_index=idx, score=0.9, metadata={},
    )


def _chatbot_row() -> MagicMock:
    row = MagicMock()
    row.id = uuid4()
    row.system_prompt = "be terse"
    row.llm_selection = LLMSelection(credential_id=uuid4(), model_id="llama3.1")
    row.pipeline_config = PipelineConfig.from_dict({})
    row.role_llm_selections = RoleLLMSelections.from_dict({})
    row.kb_ids = []
    return row


def _chatbot_repo(row: MagicMock, *, kb_ids: list[Any] | None = None) -> MagicMock:
    row.kb_ids = kb_ids if kb_ids is not None else []
    repo = MagicMock()
    repo.get_chatbot = AsyncMock(return_value=row)
    repo.list_kb_ids = AsyncMock(return_value=list(row.kb_ids))
    return repo


def _wire(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_resolve_inference_target(**kwargs: Any) -> tuple[str, str, str | None]:
        return ("ollama", "http://fake", None)

    monkeypatch.setattr(mod, "resolve_inference_target", _fake_resolve_inference_target)


class _ScriptedLLM:
    def __init__(self, *responses: Any) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._responses.pop(0)


class _Dispatcher:
    def __init__(self, llm: _ScriptedLLM) -> None:
        self._llm = llm

    def for_provider(self, provider_id: str) -> _ScriptedLLM:
        return self._llm


def _docs_llm(answer: str = "ok") -> _ScriptedLLM:
    return _ScriptedLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_DOCS, "rationale": "factual"}),
        LLMToolCall(tool=GRADE_VERDICT_TOOL, arguments={"sufficient": True}),
        LLMTextResponse(text=answer),
    )


def _normal_llm(answer: str = "ok") -> _ScriptedLLM:
    return _ScriptedLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_NORMAL, "rationale": "greeting"}),
        LLMTextResponse(text=answer),
    )


@pytest.mark.asyncio
async def test_retrieved_contexts_populated_from_docs_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On the docs route, AnswerView.retrieved_contexts contains the content
    of every retrieved chunk (in retrieval order).
    """
    _wire(monkeypatch)
    row = _chatbot_row()
    chatbot_repo = _chatbot_repo(row, kb_ids=[uuid4()])
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.name = "Handbook"
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb_row)

    chunks = [_chunk("alpha", 0), _chunk("beta", 1)]

    view = await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=kb_repo,
        sources_repo=_no_sources_repo_factory(),
        llm_dispatcher=_Dispatcher(_docs_llm()),
        retrieve_docs=AsyncMock(return_value=chunks),
        create_session=AsyncMock(return_value=uuid4()),
        append_message=AsyncMock(return_value=uuid4()),
        touch_session=AsyncMock(),
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=None, user_message="?",
    )
    assert view.retrieved_contexts == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_persist_false_skips_session_and_message_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When persist=False, create_session / append_message / touch_session
    must NOT be called. The AnswerView still has a (throwaway) session_id
    and message_id so callers don't need to deal with Optional types.
    """
    _wire(monkeypatch)
    row = _chatbot_row()
    chatbot_repo = _chatbot_repo(row, kb_ids=[])

    create = AsyncMock(return_value=uuid4())
    append = AsyncMock(return_value=uuid4())
    touch = AsyncMock()

    view = await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=MagicMock(),
        sources_repo=_no_sources_repo_factory(),
        llm_dispatcher=_Dispatcher(_normal_llm()),
        retrieve_docs=AsyncMock(return_value=[]),
        create_session=create,
        append_message=append,
        touch_session=touch,
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=None, user_message="x",
        persist=False,
    )
    create.assert_not_awaited()
    append.assert_not_awaited()
    touch.assert_not_awaited()
    assert view.content == "ok"
    assert view.session_id is not None
    assert view.message_id is not None


@pytest.mark.asyncio
async def test_persist_true_default_still_persists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: default behaviour (persist=True) must create a
    session when none is passed, then two append_message (user + assistant)
    and one touch.
    """
    _wire(monkeypatch)
    row = _chatbot_row()
    chatbot_repo = _chatbot_repo(row, kb_ids=[])

    create = AsyncMock(return_value=uuid4())
    append = AsyncMock(return_value=uuid4())
    touch = AsyncMock()

    await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=MagicMock(),
        sources_repo=_no_sources_repo_factory(),
        llm_dispatcher=_Dispatcher(_normal_llm()),
        retrieve_docs=AsyncMock(return_value=[]),
        create_session=create,
        append_message=append,
        touch_session=touch,
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=None, user_message="x",
    )
    assert create.await_count == 1
    assert append.await_count == 2  # user + assistant
    assert touch.await_count == 1
