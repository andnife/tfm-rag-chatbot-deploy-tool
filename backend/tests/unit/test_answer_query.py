from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import tfm_rag.application.chat.answer_query as mod
from tfm_rag.application.chat.answer_query import AnswerView, answer_query
from tfm_rag.domain.catalog.evaluator_schemas import ROUTE_DECISION_TOOL
from tfm_rag.domain.catalog.routes import ROUTE_DOCS, ROUTE_NORMAL
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMTextResponse,
    LLMToolCall,
    TokenUsage,
)
from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk
from tfm_rag.domain.value_objects.role_llm_selections import RoleLLMSelections
from tfm_rag.infrastructure.persistence.repository import RequestContext


def _ctx() -> RequestContext:
    return RequestContext(tenant_id=uuid4(), user_id=uuid4())


def _chunk(text: str, source: str = "manual.pdf", idx: int = 0) -> RetrievedChunk:
    return RetrievedChunk(
        point_id=f"pid-{text}-{idx}", content=text, source_id=uuid4(),
        source_filename=source, chunk_index=idx, score=0.9, metadata={},
    )


def _chatbot_row() -> MagicMock:
    # A Chatbot-entity-like fake: config fields are the typed VOs the use case
    # now reads directly off the aggregate. MagicMock keeps it mutable so tests
    # can override e.g. `.pipeline_config`.
    row = MagicMock()
    row.id = uuid4()
    row.system_prompt = "You are a helpful assistant."
    row.llm_selection = LLMSelection(credential_id=uuid4(), model_id="llama3.1")
    row.pipeline_config = PipelineConfig.from_dict({})        # defaults
    row.role_llm_selections = RoleLLMSelections.from_dict({})  # roles fall back
    row.kb_ids = []
    return row


def _chatbot_repo(row: MagicMock, *, kb_ids: list[Any] | None = None) -> MagicMock:
    row.kb_ids = kb_ids if kb_ids is not None else []
    repo = MagicMock()
    repo.get_chatbot = AsyncMock(return_value=row)
    # Legacy seam kept so the override test can assert it is never awaited.
    repo.list_kb_ids = AsyncMock(return_value=list(row.kb_ids))
    return repo


def _sources_repo_empty() -> MagicMock:
    repo = MagicMock()
    repo.list_sources_by_kb = AsyncMock(return_value=[])
    return repo


class _ScriptedLLM:
    """Returns queued responses in order across all generate() calls."""

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


def _wire(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch resolve_inference_target so no real credential lookup happens."""

    async def _fake_resolve_inference_target(**kwargs: Any) -> tuple[str, str, str | None]:
        return ("ollama", "http://fake", None)

    monkeypatch.setattr(mod, "resolve_inference_target", _fake_resolve_inference_target)


@pytest.mark.asyncio
async def test_normal_route_answers_without_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = _ScriptedLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_NORMAL, "rationale": "greeting"}),
        LLMTextResponse(text="Hi! I help with your docs."),
    )
    _wire(monkeypatch)
    row = _chatbot_row()
    chatbot_repo = _chatbot_repo(row, kb_ids=[])

    async def _no_docs(*a: Any, **k: Any) -> Any:
        raise AssertionError("retrieve_docs must not be called on normal route")

    captured: list[dict[str, Any]] = []

    async def fake_append(*a: Any, **k: Any) -> Any:
        captured.append(k)
        return uuid4()

    view = await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=MagicMock(),
        sources_repo=_sources_repo_empty(),
        llm_dispatcher=_Dispatcher(llm),
        retrieve_docs=_no_docs,
        create_session=AsyncMock(return_value=uuid4()),
        append_message=fake_append,
        touch_session=AsyncMock(),
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=None, user_message="hello",
    )
    assert isinstance(view, AnswerView)
    assert "Hi!" in view.content
    assert view.citations == []
    assert view.iterations[0].tool == ROUTE_NORMAL
    # Assistant message persisted with the routing trace.
    assistant = captured[-1]
    assert assistant["role"] == "assistant"
    assert assistant["metadata"]["routing"]["route"] == ROUTE_NORMAL


@pytest.mark.asyncio
async def test_docs_route_sufficient_first_try_cites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tfm_rag.domain.catalog.evaluator_schemas import GRADE_VERDICT_TOOL
    llm = _ScriptedLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_DOCS, "rationale": "factual"}),
        LLMToolCall(tool=GRADE_VERDICT_TOOL, arguments={"sufficient": True}),
        LLMTextResponse(text="Grounded answer."),
    )
    _wire(monkeypatch)
    row = _chatbot_row()
    chatbot_repo = _chatbot_repo(row, kb_ids=[uuid4()])
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.name = "Handbook"
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb_row)

    retrieve = AsyncMock(return_value=[_chunk("relevant text")])

    view = await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=kb_repo,
        sources_repo=_sources_repo_empty(),
        llm_dispatcher=_Dispatcher(llm),
        retrieve_docs=retrieve,
        create_session=AsyncMock(return_value=uuid4()),
        append_message=AsyncMock(return_value=uuid4()),
        touch_session=AsyncMock(),
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=None, user_message="what is X?",
    )
    assert view.content == "Grounded answer."
    assert len(view.citations) == 1
    assert view.iterations[0].tool == ROUTE_DOCS
    assert view.retrieved_contexts == ["relevant text"]


@pytest.mark.asyncio
async def test_docs_route_reformulates_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tfm_rag.domain.catalog.evaluator_schemas import GRADE_VERDICT_TOOL
    llm = _ScriptedLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_DOCS, "rationale": "factual"}),
        LLMToolCall(tool=GRADE_VERDICT_TOOL,
                    arguments={"sufficient": False,
                               "reformulated_query": "better query"}),
        LLMToolCall(tool=GRADE_VERDICT_TOOL, arguments={"sufficient": True}),
        LLMTextResponse(text="Answer after reformulation."),
    )
    _wire(monkeypatch)
    row = _chatbot_row()
    row.pipeline_config = PipelineConfig.from_dict({"max_self_correction_retries": 2})
    chatbot_repo = _chatbot_repo(row, kb_ids=[uuid4()])
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.name = "KB"
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb_row)

    seen_queries: list[str] = []

    async def _retrieve(*a: Any, **k: Any) -> Any:
        seen_queries.append(k["query"])
        return [_chunk("text")]

    view = await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=kb_repo,
        sources_repo=_sources_repo_empty(),
        llm_dispatcher=_Dispatcher(llm),
        retrieve_docs=_retrieve,
        create_session=AsyncMock(return_value=uuid4()),
        append_message=AsyncMock(return_value=uuid4()),
        touch_session=AsyncMock(),
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=None, user_message="original",
    )
    assert view.content == "Answer after reformulation."
    assert seen_queries == ["original", "better query"]


@pytest.mark.asyncio
async def test_docs_route_exhausted_abstains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tfm_rag.domain.catalog.evaluator_schemas import GRADE_VERDICT_TOOL
    llm = _ScriptedLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_DOCS, "rationale": "factual"}),
        LLMToolCall(tool=GRADE_VERDICT_TOOL,
                    arguments={"sufficient": False,
                               "abstain_reason": "nothing relevant"}),
        # Unified abstention is now generated by the answer LLM (one extra call).
        LLMTextResponse(text="No dispongo de esa información."),
    )
    _wire(monkeypatch)
    row = _chatbot_row()
    row.pipeline_config = PipelineConfig.from_dict({"max_self_correction_retries": 0})
    chatbot_repo = _chatbot_repo(row, kb_ids=[uuid4()])
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.name = "KB"
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb_row)

    view = await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=kb_repo,
        sources_repo=_sources_repo_empty(),
        llm_dispatcher=_Dispatcher(llm),
        retrieve_docs=AsyncMock(return_value=[]),
        create_session=AsyncMock(return_value=uuid4()),
        append_message=AsyncMock(return_value=uuid4()),
        touch_session=AsyncMock(),
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=None, user_message="q",
    )
    # No more hardcoded English prefix — the message is the unified LLM output.
    assert view.content == "No dispongo de esa información."
    assert "I don't know" not in view.content
    assert view.citations == []


@pytest.mark.asyncio
async def test_abstain_path_emits_synthesize_with_abstained_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """on_step synthesize detail must carry abstained=True on the abstain branch."""
    from tfm_rag.domain.catalog.evaluator_schemas import GRADE_VERDICT_TOOL

    llm = _ScriptedLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_DOCS, "rationale": "factual"}),
        LLMToolCall(tool=GRADE_VERDICT_TOOL,
                    arguments={"sufficient": False,
                               "abstain_reason": "nothing relevant"}),
        LLMTextResponse(text="No dispongo de esa información."),
    )
    _wire(monkeypatch)
    row = _chatbot_row()
    row.pipeline_config = PipelineConfig.from_dict({"max_self_correction_retries": 0})
    chatbot_repo = _chatbot_repo(row, kb_ids=[uuid4()])
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.name = "KB"
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb_row)

    recorded: list[tuple[str, dict]] = []

    async def _recorder(step: str, detail: dict) -> None:
        recorded.append((step, detail))

    view = await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=kb_repo,
        sources_repo=_sources_repo_empty(),
        llm_dispatcher=_Dispatcher(llm),
        retrieve_docs=AsyncMock(return_value=[]),
        create_session=AsyncMock(return_value=uuid4()),
        append_message=AsyncMock(return_value=uuid4()),
        touch_session=AsyncMock(),
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=None, user_message="q",
        on_step=_recorder,
    )
    assert view.content == "No dispongo de esa información."
    synthesize_events = [(s, d) for s, d in recorded if s == "synthesize"]
    assert len(synthesize_events) == 1
    _, detail = synthesize_events[0]
    assert detail.get("abstained") is True
    # The abstention now carries a real generated message, not an empty payload.
    assert detail.get("chars", 0) > 0


@pytest.mark.asyncio
async def test_sql_route_no_data_abstains_unified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQL route with no database sources → no results → unified abstention
    (no grader on the SQL sub-route, so this exercises the empty-verdicts path)."""
    from tfm_rag.domain.catalog.routes import ROUTE_SQL

    llm = _ScriptedLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_SQL, "rationale": "tabular"}),
        # No grader call for SQL; next LLM call is the unified abstention.
        LLMTextResponse(text="No hay datos para responder a eso."),
    )
    _wire(monkeypatch)
    row = _chatbot_row()
    chatbot_repo = _chatbot_repo(row, kb_ids=[uuid4()])
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.name = "KB"
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb_row)

    view = await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=kb_repo,
        sources_repo=_sources_repo_empty(),  # no database sources
        llm_dispatcher=_Dispatcher(llm),
        retrieve_docs=AsyncMock(return_value=[]),
        create_session=AsyncMock(return_value=uuid4()),
        append_message=AsyncMock(return_value=uuid4()),
        touch_session=AsyncMock(),
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=None, user_message="how many?",
    )
    assert view.content == "No hay datos para responder a eso."
    assert "I don't know" not in view.content
    assert view.citations == []


@pytest.mark.asyncio
async def test_synthesis_sentinel_redirects_to_unified_abstention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Grader says sufficient, but the answer LLM can't find it and emits the
    NO_INFO sentinel → the orchestrator redirects to the unified abstention
    instead of surfacing the raw sentinel, and drops citations."""
    from tfm_rag.application.chat.synthesize import NO_INFO_SENTINEL
    from tfm_rag.domain.catalog.evaluator_schemas import GRADE_VERDICT_TOOL

    llm = _ScriptedLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_DOCS, "rationale": "factual"}),
        LLMToolCall(tool=GRADE_VERDICT_TOOL, arguments={"sufficient": True}),
        LLMTextResponse(text=NO_INFO_SENTINEL),          # synthesis declines
        LLMTextResponse(text="No tengo ese dato en la documentación."),  # unified
    )
    _wire(monkeypatch)
    row = _chatbot_row()
    row.pipeline_config = PipelineConfig.from_dict({"max_self_correction_retries": 0})
    chatbot_repo = _chatbot_repo(row, kb_ids=[uuid4()])
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.name = "KB"
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb_row)

    view = await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=kb_repo,
        sources_repo=_sources_repo_empty(),
        llm_dispatcher=_Dispatcher(llm),
        retrieve_docs=AsyncMock(return_value=[_chunk("some excerpt")]),
        create_session=AsyncMock(return_value=uuid4()),
        append_message=AsyncMock(return_value=uuid4()),
        touch_session=AsyncMock(),
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=None, user_message="q",
    )
    assert view.content == "No tengo ese dato en la documentación."
    assert NO_INFO_SENTINEL not in view.content
    assert view.citations == []


@pytest.mark.asyncio
async def test_reuses_existing_session_when_id_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = _ScriptedLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_NORMAL, "rationale": "greeting"}),
        LLMTextResponse(text="ok"),
    )
    _wire(monkeypatch)
    row = _chatbot_row()
    chatbot_repo = _chatbot_repo(row, kb_ids=[])
    existing = uuid4()
    create = AsyncMock(return_value=uuid4())

    view = await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=MagicMock(),
        sources_repo=_sources_repo_empty(),
        llm_dispatcher=_Dispatcher(llm),
        retrieve_docs=AsyncMock(return_value=[]),
        create_session=create,
        append_message=AsyncMock(return_value=uuid4()),
        touch_session=AsyncMock(),
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=existing, user_message="x",
    )
    assert view.session_id == existing
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_answer_query_raises_when_chatbot_missing() -> None:
    ctx = _ctx()
    chatbot_repo = MagicMock()
    chatbot_repo.get_chatbot = AsyncMock(side_effect=NotFoundError("nope"))
    chatbot_repo.list_kb_ids = AsyncMock(return_value=[])

    async def fake_unused(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("should not be called")

    with pytest.raises(ChatbotNotFoundError):
        await answer_query(
            tenant_id=ctx.tenant_id,
            chatbot_repo=chatbot_repo,
            kb_repo=MagicMock(),
            sources_repo=MagicMock(),
            llm_dispatcher=MagicMock(),
            retrieve_docs=fake_unused,
            create_session=fake_unused,
            append_message=fake_unused,
            touch_session=fake_unused,
            qdrant=MagicMock(),
            embedder_dispatcher=MagicMock(),
            credentials_repo=MagicMock(), session_repo=MagicMock(),
            message_repo=MagicMock(), encryptor=MagicMock(),
            ollama_base_url="http://ollama:11434",
            chatbot_id=uuid4(),
            session_id=None,
            user_message="x",
        )


def _sources_repo_with_db(source_id: Any) -> MagicMock:
    repo = MagicMock()
    src = MagicMock()
    src.id = source_id
    src.type = "database"
    src.payload = {"driver": "postgres", "db_name": "shop",
                   "schema_snapshot": {"tables": [
                       {"schema": "public", "name": "users",
                        "columns": [{"name": "id", "data_type": "int"}]}]}}
    src.description = None
    repo.list_sources_by_kb = AsyncMock(return_value=[src])
    return repo


class _FakeSqlResult:
    def __init__(self, md: str, rows: int) -> None:
        self._md = md
        self.row_count = rows

    def to_markdown(self) -> str:
        return self._md


class _FakeSqlOut:
    def __init__(self, md: str, rows: int) -> None:
        self.result = _FakeSqlResult(md, rows)


@pytest.mark.asyncio
async def test_sql_route_generates_executes_and_synthesizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tfm_rag.domain.catalog.evaluator_schemas import RUN_QUERY_TOOL
    from tfm_rag.domain.catalog.routes import ROUTE_SQL

    source_id = uuid4()
    llm = _ScriptedLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_SQL, "rationale": "needs live data"}),
        LLMToolCall(tool=RUN_QUERY_TOOL,
                    arguments={"source_id": str(source_id),
                               "sql": "SELECT count(*) FROM users"}),
        LLMTextResponse(text="done"),          # SQL model self-terminates
        LLMTextResponse(text="There are 3 users."),  # answer_generator synthesis
    )
    _wire(monkeypatch)
    row = _chatbot_row()
    kb_id = uuid4()
    chatbot_repo = _chatbot_repo(row, kb_ids=[kb_id])
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.name = "KB"
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb_row)

    captured_sql: list[str] = []

    async def _fake_qdb(*, allowed_kb_ids: Any,
                        source_id: Any, sql: str, row_limit: int) -> Any:
        captured_sql.append(sql)
        return _FakeSqlOut("| count |\n|---|\n| 3 |", 1)

    sources_repo = _sources_repo_with_db(source_id)

    view = await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=kb_repo,
        sources_repo=sources_repo,
        llm_dispatcher=_Dispatcher(llm),
        retrieve_docs=AsyncMock(return_value=[]),
        create_session=AsyncMock(return_value=uuid4()),
        append_message=AsyncMock(return_value=uuid4()),
        touch_session=AsyncMock(),
        query_database_fn=_fake_qdb,
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=None, user_message="how many users?",
    )
    assert view.content == "There are 3 users."
    assert captured_sql == ["SELECT count(*) FROM users"]
    assert view.citations == []
    assert any("| count |" in rc for rc in view.retrieved_contexts)
    # The SQL context must carry the QUERY too, not just the bare result table —
    # otherwise the RAGAS judge can't tell whether the query makes sense or
    # whether the returned value answers the question (a bare "| 3 |" has no
    # semantics). Enriching it fixes faithfulness/context scoring for SQL.
    assert any("SELECT count(*) FROM users" in rc for rc in view.retrieved_contexts)


@pytest.mark.asyncio
async def test_sql_route_reinjects_execution_error_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tfm_rag.domain.catalog.evaluator_schemas import RUN_QUERY_TOOL
    from tfm_rag.domain.catalog.routes import ROUTE_SQL
    from tfm_rag.domain.errors.chat import QueryExecutionError

    source_id = uuid4()
    llm = _ScriptedLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_SQL, "rationale": "live data"}),
        LLMToolCall(tool=RUN_QUERY_TOOL,
                    arguments={"source_id": str(source_id),
                               "sql": "SELECT * FROM userz"}),   # fails → error fed back
        LLMToolCall(tool=RUN_QUERY_TOOL,
                    arguments={"source_id": str(source_id),
                               "sql": "SELECT * FROM users"}),   # self-corrected
        LLMTextResponse(text="done"),          # SQL model self-terminates
        LLMTextResponse(text="Fixed answer."),  # synthesis
    )
    _wire(monkeypatch)
    row = _chatbot_row()
    row.pipeline_config = PipelineConfig.from_dict({"max_self_correction_retries": 2})
    chatbot_repo = _chatbot_repo(row, kb_ids=[uuid4()])
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.name = "KB"
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb_row)

    attempts: list[str] = []

    async def _fake_qdb(*, allowed_kb_ids: Any,
                        source_id: Any, sql: str, row_limit: int) -> Any:
        attempts.append(sql)
        if "userz" in sql:
            raise QueryExecutionError("relation userz does not exist")
        return _FakeSqlOut("| id |\n|---|\n| 1 |", 1)

    view = await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=kb_repo,
        sources_repo=_sources_repo_with_db(source_id),
        llm_dispatcher=_Dispatcher(llm),
        retrieve_docs=AsyncMock(return_value=[]),
        create_session=AsyncMock(return_value=uuid4()),
        append_message=AsyncMock(return_value=uuid4()),
        touch_session=AsyncMock(),
        query_database_fn=_fake_qdb,
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=None, user_message="list users",
    )
    assert view.content == "Fixed answer."
    assert attempts == ["SELECT * FROM userz", "SELECT * FROM users"]


@pytest.mark.asyncio
async def test_both_route_combines_docs_and_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tfm_rag.domain.catalog.evaluator_schemas import (
        GRADE_VERDICT_TOOL,
        RUN_QUERY_TOOL,
    )
    from tfm_rag.domain.catalog.routes import ROUTE_BOTH

    source_id = uuid4()

    # `both` runs docs then sql, then a single synthesis. Dispatch the response
    # by which tool is offered (or text when no tools = synthesis / SQL self-
    # termination). The SQL thread must stop after its first query, so run_query
    # is answered once and then with plain text.
    class _ToolRoutedLLM:
        def __init__(self) -> None:
            self._sql_queries = 0

        async def generate(self, **kwargs: Any) -> Any:
            tools = kwargs.get("tools")
            if not tools:
                return LLMTextResponse(text="Combined answer.")
            name = tools[0]["function"]["name"]
            if name == ROUTE_DECISION_TOOL:
                return LLMToolCall(tool=ROUTE_DECISION_TOOL,
                                   arguments={"route": ROUTE_BOTH,
                                              "rationale": "docs + data"})
            if name == RUN_QUERY_TOOL:
                if self._sql_queries == 0:
                    self._sql_queries += 1
                    return LLMToolCall(tool=RUN_QUERY_TOOL,
                                       arguments={"source_id": str(source_id),
                                                  "sql": "SELECT count(*) FROM users"})
                return LLMTextResponse(text="done")  # SQL self-terminates
            return LLMToolCall(tool=GRADE_VERDICT_TOOL,
                               arguments={"sufficient": True})

    llm = _ToolRoutedLLM()
    _wire(monkeypatch)
    row = _chatbot_row()
    row.pipeline_config = PipelineConfig.from_dict({"max_self_correction_retries": 0})
    chatbot_repo = _chatbot_repo(row, kb_ids=[uuid4()])
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.name = "KB"
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb_row)

    async def _fake_qdb(*, allowed_kb_ids: Any,
                        source_id: Any, sql: str, row_limit: int) -> Any:
        return _FakeSqlOut("| count |\n|---|\n| 3 |", 1)

    async def _retrieve(*a: Any, **k: Any) -> Any:
        return [_chunk("doc text")]

    view = await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=kb_repo,
        sources_repo=_sources_repo_with_db(source_id),
        llm_dispatcher=_Dispatcher(llm),
        retrieve_docs=_retrieve,
        create_session=AsyncMock(return_value=uuid4()),
        append_message=AsyncMock(return_value=uuid4()),
        touch_session=AsyncMock(),
        query_database_fn=_fake_qdb,
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=None, user_message="q",
    )
    assert view.content == "Combined answer."
    assert len(view.citations) == 1            # from the doc chunk
    assert any("| count |" in rc for rc in view.retrieved_contexts)
    assert any(rc == "doc text" for rc in view.retrieved_contexts)


@pytest.mark.asyncio
async def test_answer_view_exposes_routing_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = _ScriptedLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_NORMAL, "rationale": "greeting"}),
        LLMTextResponse(text="Hi!"),
    )
    _wire(monkeypatch)
    row = _chatbot_row()
    chatbot_repo = _chatbot_repo(row, kb_ids=[])

    view = await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=MagicMock(),
        sources_repo=_sources_repo_empty(),
        llm_dispatcher=_Dispatcher(llm),
        retrieve_docs=AsyncMock(),
        create_session=AsyncMock(return_value=uuid4()),
        append_message=AsyncMock(return_value=uuid4()),
        touch_session=AsyncMock(),
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=None, user_message="hello",
    )
    assert view.routing_trace["route"] == ROUTE_NORMAL
    assert view.routing_trace["rationale"] == "greeting"
    assert "attempts" in view.routing_trace and "verdicts" in view.routing_trace


@pytest.mark.asyncio
async def test_router_disabled_forces_docs_without_route_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tfm_rag.domain.catalog.evaluator_schemas import GRADE_VERDICT_TOOL
    llm = _ScriptedLLM(
        LLMToolCall(tool=GRADE_VERDICT_TOOL, arguments={"sufficient": True}),
        LLMTextResponse(text="Answer from docs."),
    )
    _wire(monkeypatch)
    row = _chatbot_row()
    chatbot_repo = _chatbot_repo(row, kb_ids=[uuid4()])
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.name = "KB"
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb_row)

    view = await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=kb_repo,
        sources_repo=_sources_repo_empty(),
        llm_dispatcher=_Dispatcher(llm),
        retrieve_docs=AsyncMock(return_value=[_chunk("relevant text")]),
        create_session=AsyncMock(return_value=uuid4()),
        append_message=AsyncMock(return_value=uuid4()),
        touch_session=AsyncMock(),
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=None, user_message="what is X?",
        router_disabled=True,
    )
    assert view.routing_trace["route"] == ROUTE_DOCS
    assert "disabled" in view.routing_trace["rationale"].lower()
    assert view.content == "Answer from docs."
    # El primer (y único) tool-call consumido fue el grade, no el route.
    assert llm.calls[0]["tools"][0]["function"]["name"] != ROUTE_DECISION_TOOL


@pytest.mark.asyncio
async def test_kb_ids_override_bypasses_chatbot_kb_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When kb_ids_override is passed, retrieval uses the override IDs and
    list_kb_ids on the chatbot repo is NOT called."""

    from tfm_rag.domain.catalog.evaluator_schemas import GRADE_VERDICT_TOOL

    kb_a = uuid4()  # chatbot's KB — must NOT be used
    kb_b = uuid4()  # override KB — must be used

    llm = _ScriptedLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_DOCS, "rationale": "factual"}),
        LLMToolCall(tool=GRADE_VERDICT_TOOL, arguments={"sufficient": True}),
        LLMTextResponse(text="Override answer."),
    )
    _wire(monkeypatch)
    row = _chatbot_row()
    chatbot_repo = _chatbot_repo(row, kb_ids=[kb_a])
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.name = "OverrideKB"
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb_row)

    captured_kb_ids: list[Any] = []

    async def _fake_retrieve(*a: Any, **k: Any) -> Any:
        captured_kb_ids.extend(k.get("kb_ids", []))
        return [_chunk("override text")]

    view = await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=kb_repo,
        sources_repo=_sources_repo_empty(),
        llm_dispatcher=_Dispatcher(llm),
        retrieve_docs=_fake_retrieve,
        create_session=AsyncMock(return_value=uuid4()),
        append_message=AsyncMock(return_value=uuid4()),
        touch_session=AsyncMock(),
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=None, user_message="what is X?",
        kb_ids_override=[kb_b],
    )
    assert view.content == "Override answer."
    # Retrieval ran against the override KB, not the chatbot's KB.
    assert captured_kb_ids == [kb_b]
    assert kb_a not in captured_kb_ids
    # list_kb_ids was NOT consulted because the override short-circuits it.
    chatbot_repo.list_kb_ids.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_step_callback_called_for_docs_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """on_step records the stage sequence for a docs-route question."""
    from tfm_rag.domain.catalog.evaluator_schemas import GRADE_VERDICT_TOOL

    llm = _ScriptedLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_DOCS, "rationale": "factual"}),
        LLMToolCall(tool=GRADE_VERDICT_TOOL, arguments={"sufficient": True}),
        LLMTextResponse(text="Grounded answer."),
    )
    _wire(monkeypatch)
    row = _chatbot_row()
    chatbot_repo = _chatbot_repo(row, kb_ids=[uuid4()])
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.name = "Handbook"
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb_row)

    steps: list[str] = []

    async def _recorder(step: str, detail: dict) -> None:
        steps.append(step)

    view = await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=kb_repo,
        sources_repo=_sources_repo_empty(),
        llm_dispatcher=_Dispatcher(llm),
        retrieve_docs=AsyncMock(return_value=[_chunk("relevant text")]),
        create_session=AsyncMock(return_value=uuid4()),
        append_message=AsyncMock(return_value=uuid4()),
        touch_session=AsyncMock(),
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=None, user_message="what is X?",
        on_step=_recorder,
    )
    assert isinstance(view, AnswerView)
    assert steps == ["route", "retrieve", "grade", "synthesize"]


@pytest.mark.asyncio
async def test_on_step_none_default_is_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calling answer_query without on_step (default None) must work as before."""
    from tfm_rag.domain.catalog.evaluator_schemas import GRADE_VERDICT_TOOL

    llm = _ScriptedLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_DOCS, "rationale": "factual"}),
        LLMToolCall(tool=GRADE_VERDICT_TOOL, arguments={"sufficient": True}),
        LLMTextResponse(text="No callback answer."),
    )
    _wire(monkeypatch)
    row = _chatbot_row()
    chatbot_repo = _chatbot_repo(row, kb_ids=[uuid4()])
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.name = "Handbook"
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb_row)

    view = await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=kb_repo,
        sources_repo=_sources_repo_empty(),
        llm_dispatcher=_Dispatcher(llm),
        retrieve_docs=AsyncMock(return_value=[_chunk("relevant text")]),
        create_session=AsyncMock(return_value=uuid4()),
        append_message=AsyncMock(return_value=uuid4()),
        touch_session=AsyncMock(),
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=None, user_message="what is X?",
        # on_step omitted — must default to None, no error
    )
    assert view.content == "No callback answer."


@pytest.mark.asyncio
async def test_answer_view_token_counts_sum_all_llm_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AnswerView.prompt_tokens / completion_tokens must equal the SUM of
    TokenUsage across every LLM call made during the pipeline.

    Normal-route path: 2 calls (route-decision + synthesis).
      call 1 (route decision): prompt=10, completion=3
      call 2 (synthesis):      prompt=20, completion=7
    Expected totals:           prompt=30, completion=10
    """
    llm = _ScriptedLLM(
        LLMToolCall(
            tool=ROUTE_DECISION_TOOL,
            arguments={"route": ROUTE_NORMAL, "rationale": "greeting"},
            usage=TokenUsage(prompt_tokens=10, completion_tokens=3),
        ),
        LLMTextResponse(
            text="Hello!",
            usage=TokenUsage(prompt_tokens=20, completion_tokens=7),
        ),
    )
    _wire(monkeypatch)
    row = _chatbot_row()
    chatbot_repo = _chatbot_repo(row, kb_ids=[])

    view = await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=MagicMock(),
        sources_repo=_sources_repo_empty(),
        llm_dispatcher=_Dispatcher(llm),
        retrieve_docs=AsyncMock(return_value=[]),
        create_session=AsyncMock(return_value=uuid4()),
        append_message=AsyncMock(return_value=uuid4()),
        touch_session=AsyncMock(),
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=None, user_message="hello",
    )

    assert view.prompt_tokens == 10 + 20      # 30
    assert view.completion_tokens == 3 + 7    # 10


# ─── SQL route: conversational thread with self-termination ─────────────────

from tfm_rag.domain.catalog.evaluator_schemas import (  # noqa: E402
    RUN_QUERY_TOOL,
)
from tfm_rag.domain.catalog.routes import ROUTE_SQL  # noqa: E402


class _FakeResult:
    def __init__(self, md: str, row_count: int) -> None:
        self._md = md
        self.row_count = row_count

    def to_markdown(self) -> str:
        return self._md


class _FakeOut:
    def __init__(self, md: str, row_count: int) -> None:
        self.result = _FakeResult(md, row_count)


class _FakeQueryDB:
    """Returns queued results in order; records the SQL of each call. A queued
    item that is an Exception instance is raised (to simulate a failed query)."""

    def __init__(self, *results: Any) -> None:
        self._results = list(results)
        self.sqls: list[str] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.sqls.append(kwargs["sql"])
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _db_source_row(sid: Any) -> MagicMock:
    row = MagicMock()
    row.id = sid
    row.type = "database"
    row.payload = {
        "driver": "mysql", "db_name": "world",
        "schema_snapshot": {"tables": [{
            "schema": "world", "name": "countries",
            "columns": [{"name": "continent", "type": "varchar"},
                        {"name": "population", "type": "bigint"}],
        }]},
    }
    row.description = None
    return row


def _sources_repo_with_db(sid: Any) -> MagicMock:
    repo = MagicMock()
    repo.list_sources_by_kb = AsyncMock(return_value=[_db_source_row(sid)])
    return repo


async def _run_sql_route(
    monkeypatch: pytest.MonkeyPatch,
    llm: _ScriptedLLM,
    query_db: _FakeQueryDB,
    *,
    user_message: str,
) -> AnswerView:
    _wire(monkeypatch)
    sid = uuid4()
    # Make the scripted run_query calls target this source id by rewriting args.
    for resp in llm._responses:
        if isinstance(resp, LLMToolCall) and resp.tool == RUN_QUERY_TOOL:
            resp.arguments["source_id"] = str(sid)
    row = _chatbot_row()
    kb_id = uuid4()
    chatbot_repo = _chatbot_repo(row, kb_ids=[kb_id])
    kb_repo = MagicMock()
    kb_row = MagicMock()
    kb_row.name = "World DB"
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb_row)
    return await answer_query(
        tenant_id=_ctx().tenant_id,
        chatbot_repo=chatbot_repo,
        kb_repo=kb_repo,
        sources_repo=_sources_repo_with_db(sid),
        llm_dispatcher=_Dispatcher(llm),
        retrieve_docs=AsyncMock(return_value=[]),
        create_session=AsyncMock(return_value=uuid4()),
        append_message=AsyncMock(return_value=uuid4()),
        touch_session=AsyncMock(),
        query_database_fn=query_db,
        qdrant=MagicMock(), embedder_dispatcher=MagicMock(),
        credentials_repo=MagicMock(), session_repo=MagicMock(),
        message_repo=MagicMock(), encryptor=MagicMock(),
        ollama_base_url="http://ollama:11434",
        chatbot_id=row.id, session_id=None, user_message=user_message,
    )


@pytest.mark.asyncio
async def test_sql_route_direct_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    # One query, then the model self-terminates (plain text) → synthesis.
    llm = _ScriptedLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_SQL, "rationale": "db"}),
        LLMToolCall(tool=RUN_QUERY_TOOL,
                    arguments={"sql": "SELECT COUNT(*) FROM countries"}),
        LLMTextResponse(text="done"),      # self-termination
        LLMTextResponse(text="195."),      # synthesis
    )
    query_db = _FakeQueryDB(_FakeOut("| count |\n|---|\n| 195 |", 1))
    view = await _run_sql_route(monkeypatch, llm, query_db, user_message="how many countries?")
    assert view.content == "195."
    assert query_db.sqls == ["SELECT COUNT(*) FROM countries"]


@pytest.mark.asyncio
async def test_sql_route_explores_then_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    # Two queries gather data (a DISTINCT to learn the stored value, then the
    # count). Both results are handed to synthesis — every query gathers info.
    llm = _ScriptedLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_SQL, "rationale": "db"}),
        LLMToolCall(tool=RUN_QUERY_TOOL, arguments={
            "sql": "SELECT DISTINCT continent FROM countries"}),
        LLMToolCall(tool=RUN_QUERY_TOOL, arguments={
            "sql": "SELECT COUNT(*) FROM countries WHERE continent='Europa'"}),
        LLMTextResponse(text="done"),          # self-termination
        LLMTextResponse(text="There are 6."),  # synthesis
    )
    query_db = _FakeQueryDB(
        _FakeOut("| continent |\n|---|\n| Europa |", 5),
        _FakeOut("| count |\n|---|\n| 6 |", 1),
    )
    view = await _run_sql_route(monkeypatch, llm, query_db, user_message="how many in Europe?")

    assert view.content == "There are 6."
    assert query_db.sqls == [
        "SELECT DISTINCT continent FROM countries",
        "SELECT COUNT(*) FROM countries WHERE continent='Europa'",
    ]
    assert any("| count |\n|---|\n| 6 |" in rc for rc in view.retrieved_contexts)
    sql_iters = [it for it in view.iterations if it.tool == ROUTE_SQL and it.sql]
    assert len(sql_iters) == 2
    assert sql_iters[0].sql.startswith("SELECT DISTINCT")


@pytest.mark.asyncio
async def test_sql_query_budget_caps_at_five(monkeypatch: pytest.MonkeyPatch) -> None:
    # The model keeps querying; the loop caps it at SQL_QUERY_BUDGET (5) and then
    # synthesizes from what it has, never running a 6th query.
    responses = [LLMToolCall(tool=ROUTE_DECISION_TOOL,
                             arguments={"route": ROUTE_SQL, "rationale": "db"})]
    for _ in range(5):
        responses.append(LLMToolCall(tool=RUN_QUERY_TOOL, arguments={
            "sql": "SELECT DISTINCT continent FROM countries"}))
    responses.append(LLMTextResponse(text="6."))  # synthesis (loop already ended)
    llm = _ScriptedLLM(*responses)
    query_db = _FakeQueryDB(
        *[_FakeOut("| continent |\n|---|\n| Europa |", 5) for _ in range(5)],
    )
    view = await _run_sql_route(monkeypatch, llm, query_db, user_message="q")
    assert view.content == "6."
    assert len(query_db.sqls) == 5  # capped — no 6th query


@pytest.mark.asyncio
async def test_sql_query_failure_reinjected_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A failed query's error is fed back into the thread; the model self-corrects
    # on its next turn (no separate self-correction loop).
    from tfm_rag.domain.errors.chat import QueryExecutionError
    llm = _ScriptedLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_SQL, "rationale": "db"}),
        LLMToolCall(tool=RUN_QUERY_TOOL, arguments={
            "sql": "SELECT COUNT(*) FROM contries"}),   # typo → fails
        LLMToolCall(tool=RUN_QUERY_TOOL, arguments={
            "sql": "SELECT COUNT(*) FROM countries"}),  # corrected
        LLMTextResponse(text="done"),
        LLMTextResponse(text="195."),
    )
    query_db = _FakeQueryDB(
        QueryExecutionError("no such table: contries"),
        _FakeOut("| count |\n|---|\n| 195 |", 1),
    )
    view = await _run_sql_route(monkeypatch, llm, query_db, user_message="q")
    assert view.content == "195."
    assert len(query_db.sqls) == 2
    failed_iter = [it for it in view.iterations if it.sql and it.row_count is None]
    assert failed_iter and "query failed" in (failed_iter[0].result_preview or "")
    # Only the successful query's result is a synthesis context.
    assert any("| count |\n|---|\n| 195 |" in rc for rc in view.retrieved_contexts)


@pytest.mark.asyncio
async def test_sql_abstains_when_no_query_returns_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Every query fails and the model gives up → no results → the pipeline
    # abstains (there is no grader to drive it; emptiness of results does).
    from tfm_rag.domain.errors.chat import QueryExecutionError
    llm = _ScriptedLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_SQL, "rationale": "db"}),
        LLMToolCall(tool=RUN_QUERY_TOOL, arguments={
            "sql": "SELECT * FROM missing"}),
        LLMTextResponse(text="I could not find the data."),  # gives up
        LLMTextResponse(text="No he podido obtener ese dato."),  # unified abstention
    )
    query_db = _FakeQueryDB(QueryExecutionError("no such table: missing"))
    view = await _run_sql_route(monkeypatch, llm, query_db, user_message="q")
    assert view.content == "No he podido obtener ese dato."
    assert "I don't know" not in view.content
    assert view.citations == []
