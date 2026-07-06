import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from tfm_rag.application.chat.append_message import append_message as _real_append_message
from tfm_rag.application.chat.create_session import create_session as _real_create_session
from tfm_rag.application.chat.generate_sql import (
    build_initial_sql_messages,
    request_next_query,
)
from tfm_rag.application.chat.grade import grade_context
from tfm_rag.application.chat.metering import MeteringLLM, TokenMeter
from tfm_rag.application.chat.retrieve_docs import retrieve_docs as _real_retrieve_docs
from tfm_rag.application.chat.route import evaluate_route
from tfm_rag.application.chat.routing_context import build_routing_context, doc_label
from tfm_rag.application.chat.synthesize import synthesize_answer
from tfm_rag.application.chat.system_prompt import render_sql_schema
from tfm_rag.application.chat.touch_session import touch_session as _real_touch_session
from tfm_rag.application.integrations.endpoint_resolver import resolve_inference_target
from tfm_rag.domain.catalog.llm_roles import (
    ROLE_ANSWER_GENERATOR,
    ROLE_EVALUATOR,
    ROLE_SQL_GENERATOR,
)
from tfm_rag.domain.catalog.routes import (
    ROUTE_BOTH,
    ROUTE_DOCS,
    ROUTE_NORMAL,
    ROUTE_SQL,
)
from tfm_rag.domain.errors.chat import (
    DatabaseSourceMismatchError,
    QueryExecutionError,
    UnsafeSQLError,
)
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import DatabaseConnectionError
from tfm_rag.domain.ports.embedder import EmbedderDispatcherPort
from tfm_rag.domain.ports.llm import LLMDispatcherPort
from tfm_rag.domain.ports.repositories import (
    ChatbotRepositoryPort,
    ChatMessageRepositoryPort,
    ChatSessionRepositoryPort,
    KnowledgeBaseRepositoryPort,
    ProviderCredentialRepositoryPort,
    SourceRepositoryPort,
)
from tfm_rag.domain.ports.secret_encryptor import SecretEncryptor
from tfm_rag.domain.ports.vector_store import VectorStorePort
from tfm_rag.domain.value_objects.citation import Citation
from tfm_rag.domain.value_objects.grade_verdict import GradeVerdict
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.retrieval_iteration import RetrievalIteration
from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk
from tfm_rag.domain.value_objects.route_decision import RouteDecision
from tfm_rag.domain.value_objects.routing_trace import RoutingTrace
from tfm_rag.domain.value_objects.sql_plan import SqlPlan

_log = logging.getLogger(__name__)

_SQL_ROW_LIMIT = 50
# Safety cap on how many queries the sql_generator may run in one thread before
# we force it to stop and synthesize from whatever it has. It normally stops
# earlier on its own (self-termination). No explore/answer split: every query
# just gathers data, and a failed query's error is fed back for self-correction.
SQL_QUERY_BUDGET = 5

RetrieveDocs = Callable[..., Awaitable[list[RetrievedChunk]]]
CreateSession = Callable[..., Awaitable[UUID]]
AppendMessage = Callable[..., Awaitable[UUID]]
TouchSession = Callable[..., Awaitable[None]]
# Router-bound closure: (allowed_kb_ids, source_id, sql, row_limit) -> output
# with a `.result` carrying `.row_count` + `.to_markdown()`.
QueryDatabaseFn = Callable[..., Awaitable[Any]]


async def _no_query_database(**_kwargs: Any) -> Any:
    """Default for `query_database_fn`: the SQL route is only reachable when the
    edge (router) has supplied a real, dependency-bound query executor. Non-SQL
    routes never invoke it, so plain/docs callers may omit it."""
    raise RuntimeError(
        "answer_query: the SQL route requires a query_database_fn to be provided"
    )


@dataclass(frozen=True, slots=True)
class AnswerView:
    session_id: UUID
    message_id: UUID
    content: str
    citations: list[Citation]
    iterations: list[RetrievalIteration]
    retrieved_contexts: list[str] = field(default_factory=list, hash=False)
    routing_trace: dict[str, Any] = field(default_factory=dict, hash=False)
    prompt_tokens: int = 0
    completion_tokens: int = 0


async def answer_query(
    *,
    tenant_id: UUID,
    chatbot_repo: ChatbotRepositoryPort,
    kb_repo: KnowledgeBaseRepositoryPort,
    sources_repo: SourceRepositoryPort,
    credentials_repo: ProviderCredentialRepositoryPort,
    session_repo: ChatSessionRepositoryPort,
    message_repo: ChatMessageRepositoryPort,
    llm_dispatcher: LLMDispatcherPort,
    embedder_dispatcher: EmbedderDispatcherPort,
    qdrant: VectorStorePort,
    encryptor: SecretEncryptor,
    ollama_base_url: str,
    retrieve_docs: RetrieveDocs = _real_retrieve_docs,
    create_session: CreateSession = _real_create_session,
    append_message: AppendMessage = _real_append_message,
    touch_session: TouchSession = _real_touch_session,
    query_database_fn: QueryDatabaseFn = _no_query_database,
    chatbot_id: UUID,
    session_id: UUID | None,
    user_message: str,
    persist: bool = True,
    session_origin: Literal["playground", "widget"] = "playground",
    public_session_cookie: str | None = None,
    router_disabled: bool = False,
    kb_ids_override: list[UUID] | None = None,
    on_step: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
) -> AnswerView:
    """Explicit-router use case (sub-proyecto B1): answers `user_message` for
    `chatbot_id`, persisting both user + assistant turns to the session.

    Workflow:
      1. Load chatbot (tenant-scoped). Build LLMSelection + PipelineConfig +
         per-role selections.
      2. If no session_id, create a session.
      3. Append user message.
      4. ROUTE: the `evaluator` role classifies the question into `normal` or
         `docs` (`sql`/`both` arrive in B2; `allow_sql=False` here).
      5. Execute the route: `docs` retrieves chunks; `normal` skips retrieval.
         A `docs` route with zero chunks abstains when configured.
      6. Synthesize the answer with the `answer_generator` role.
      7. Append assistant message with the RoutingTrace metadata + touch session.
    """
    meter = TokenMeter()

    async def _emit(step: str, **detail: Any) -> None:
        if on_step is not None:
            await on_step(step, detail)

    # --- Step 1: load chatbot ---
    try:
        chatbot = await chatbot_repo.get_chatbot(chatbot_id)
    except NotFoundError as exc:
        raise ChatbotNotFoundError(str(exc)) from exc
    kb_ids = kb_ids_override if kb_ids_override is not None else chatbot.kb_ids

    llm_selection = chatbot.llm_selection
    pipeline = chatbot.pipeline_config
    roles = chatbot.role_llm_selections
    eval_sel = roles.resolve(ROLE_EVALUATOR, llm_selection)
    ans_sel = roles.resolve(ROLE_ANSWER_GENERATOR, llm_selection)
    sql_sel = roles.resolve(ROLE_SQL_GENERATOR, llm_selection)

    # Load the chatbot's KB sources so we can include DB schemas in the routing
    # context. Only `type='database'` entries contribute the SQL block.
    all_sources: list[dict[str, Any]] = []
    for kb_id in kb_ids:
        for src in await sources_repo.list_sources_by_kb(kb_id):
            all_sources.append({
                "source_id": src.id,
                "type": src.type,
                "payload": dict(src.payload or {}),
                "description": src.description,
            })

    # The synthesis system prompt is the chatbot's editable persona ONLY. The
    # DB schema is deliberately NOT injected here: synthesis just formats data
    # already gathered by the SQL sub-route, so the (large) schema block would
    # be dead weight. It used to be appended on EVERY question — even pure docs
    # questions that never touch SQL — which dominated the per-question token
    # bill. The full schema now lives solely inside the SQL sub-route thread.
    base_system_prompt = chatbot.system_prompt or ""

    # --- Step 2: ensure a session exists ---
    if session_id is None:
        if persist:
            session_id = await create_session(
                chatbot_repo=chatbot_repo,
                session_repo=session_repo,
                chatbot_id=chatbot_id,
                origin=session_origin,
                public_session_cookie=public_session_cookie,
            )
        else:
            # Throwaway UUID — no DB row exists. Eval flows don't read
            # session_id off the view; keep the type non-Optional so the
            # HTTP path doesn't have to deal with None.
            from uuid import uuid4 as _uuid4
            session_id = _uuid4()

    # --- Step 3: append user message ---
    if persist:
        await append_message(
            session_repo=session_repo,
            message_repo=message_repo,
            session_id=session_id,
            role="user",
            content=user_message,
            citations=None,
            metadata=None,
        )

    # --- Resolve per-role endpoints ---
    async def _open(sel: LLMSelection) -> tuple[Any, str, str | None]:
        provider_id, base_url, api_key = await resolve_inference_target(
            credential_id=sel.credential_id,
            credentials_repo=credentials_repo,
            encryptor=encryptor,
            ollama_base_url=ollama_base_url,
        )
        provider_llm = llm_dispatcher.for_provider(provider_id)
        return MeteringLLM(provider_llm, meter), base_url, api_key

    # --- Build routing context (lightweight docs signal + sql schema) ---
    kb_names: list[str] = []
    for kb_id in kb_ids:
        try:
            kb = await kb_repo.get_knowledge_base(kb_id)
            kb_names.append(kb.name)
        except Exception:  # pragma: no cover - defensive
            kb_names.append(str(kb_id))
    doc_labels = [
        doc_label(
            filename=str(s["payload"].get("filename")
                         or s["payload"].get("name") or s["source_id"]),
            description=s.get("description"),
        )
        for s in all_sources if s["type"] != "database"
    ]
    routing_context = build_routing_context(
        kb_names=kb_names, doc_source_labels=doc_labels, db_sources=all_sources,
    )

    # --- Step 4: ROUTE ---
    eval_llm, eval_url, eval_key = await _open(eval_sel)
    if router_disabled:
        decision = RouteDecision(
            route=ROUTE_DOCS,
            rationale="router disabled (baseline)",
        )
    else:
        decision = await evaluate_route(
            llm=eval_llm, base_url=eval_url, api_key=eval_key,
            model_id=eval_sel.model_id, generation=pipeline.generation,
            user_message=user_message, routing_context=routing_context,
            allow_sql=True,
        )

    await _emit("route", route=decision.route)

    budget = pipeline.max_self_correction_retries

    async def _run_docs_subroute() -> tuple[
        list[RetrievedChunk], list[str],
        list[RetrievalIteration], list[GradeVerdict],
    ]:
        iters: list[RetrievalIteration] = []
        verds: list[GradeVerdict] = []
        chunks_acc: list[RetrievedChunk] = []
        query = user_message
        for attempt in range(budget + 1):
            t0 = time.perf_counter()
            chunks_acc = await retrieve_docs(
                tenant_id=tenant_id, qdrant=qdrant,
                dispatcher=embedder_dispatcher, kb_repo=kb_repo,
                credentials_repo=credentials_repo, encryptor=encryptor,
                ollama_base_url=ollama_base_url, kb_ids=kb_ids, query=query,
                top_k=pipeline.top_k,
                score_threshold=(pipeline.score_threshold
                                 if pipeline.score_threshold > 0.0 else None),
            )
            iters.append(RetrievalIteration(
                index=attempt, tool=ROUTE_DOCS, query=query,
                num_chunks=len(chunks_acc),
                latency_ms=(time.perf_counter() - t0) * 1000.0,
            ))
            context_text = (
                "\n\n".join(c.content for c in chunks_acc)
                if chunks_acc else "(no relevant documents found)"
            )
            can_reformulate = attempt < budget
            verdict = await grade_context(
                llm=eval_llm, base_url=eval_url, api_key=eval_key,
                model_id=eval_sel.model_id, generation=pipeline.generation,
                route=ROUTE_DOCS, user_message=user_message,
                context_text=context_text, can_reformulate=can_reformulate,
            )
            verds.append(verdict)
            if (verdict.sufficient or not can_reformulate
                    or not verdict.reformulated_query):
                break
            query = verdict.reformulated_query
        await _emit("retrieve", num_chunks=len(chunks_acc))
        return chunks_acc, [], iters, verds

    sql_schema_context = render_sql_schema(all_sources)
    allowed_source_ids = tuple(
        s["source_id"] for s in all_sources if s["type"] == "database"
    )

    async def _run_sql_subroute() -> tuple[
        list[RetrievedChunk], list[str],
        list[RetrievalIteration], list[GradeVerdict],
    ]:
        """Conversational SQL thread: the sql_generator runs queries one at a
        time (each result fed back) and self-terminates when it has enough data.
        No grader here — the answer_generator synthesizes from the accumulated
        results, and abstention falls out of there being no results at all."""
        iters: list[RetrievalIteration] = []
        verds: list[GradeVerdict] = []  # the SQL route has no grader
        if not allowed_source_ids:
            return [], [], iters, verds
        sql_llm, sql_url, sql_key = await _open(sql_sel)

        async def _execute(plan: SqlPlan) -> tuple[str, int | None, float]:
            """Run a plan's SQL. Returns (result_markdown, row_count, latency_ms);
            row_count is None if execution failed (markdown carries the error)."""
            t0 = time.perf_counter()
            try:
                out = await query_database_fn(
                    allowed_kb_ids=tuple(kb_ids), source_id=plan.source_id,
                    sql=plan.sql, row_limit=_SQL_ROW_LIMIT,
                )
            except (UnsafeSQLError, QueryExecutionError,
                    DatabaseSourceMismatchError, DatabaseConnectionError) as exc:
                return (f"(query failed: {type(exc).__name__}: {exc})", None,
                        (time.perf_counter() - t0) * 1000.0)
            return (out.result.to_markdown(), out.result.row_count,
                    (time.perf_counter() - t0) * 1000.0)

        messages = build_initial_sql_messages(
            schema_context=sql_schema_context, user_message=user_message,
            allowed_source_ids=allowed_source_ids,
        )
        sql_contexts: list[str] = []
        for _turn in range(SQL_QUERY_BUDGET):
            kind, plan = await request_next_query(
                llm=sql_llm, base_url=sql_url, api_key=sql_key,
                model_id=sql_sel.model_id, generation=pipeline.generation,
                messages=messages, allowed_source_ids=allowed_source_ids,
            )
            if kind == "done" or plan is None:
                break
            md, row_count, latency = await _execute(plan)
            iters.append(RetrievalIteration(
                index=len(iters), tool=ROUTE_SQL, query=None, num_chunks=None,
                latency_ms=latency, sql=plan.sql, row_count=row_count,
                result_preview=md[:2000],
            ))
            # Feed the query + its result back into the thread. A failed query's
            # error is fed back too → the model self-corrects on the next turn.
            messages.append({"role": "assistant", "content": plan.sql})
            messages.append({"role": "user", "content": f"Result:\n{md[:2000]}"})
            if row_count is not None:
                # Pair the query with its result: a bare result table (e.g.
                # "| COUNT(*) | 7 |") has no semantics on its own, so downstream
                # synthesis and the RAGAS judge can't tell what it means.
                sql_contexts.append(f"SQL query:\n{plan.sql}\nResult:\n{md}")
        await _emit("sql", row_count=(iters[-1].row_count if iters else None))
        return [], sql_contexts, iters, verds

    chunks: list[RetrievedChunk] = []
    sql_contexts: list[str] = []
    iterations: list[RetrievalIteration] = []
    verdicts: list[GradeVerdict] = []

    if decision.route == ROUTE_NORMAL:
        iterations.append(RetrievalIteration(
            index=0, tool=ROUTE_NORMAL, query=None, num_chunks=None,
            latency_ms=0.0,
        ))
    elif decision.route == ROUTE_DOCS:
        chunks, sql_contexts, iterations, verdicts = await _run_docs_subroute()
    elif decision.route == ROUTE_SQL:
        chunks, sql_contexts, iterations, verdicts = await _run_sql_subroute()
    elif decision.route == ROUTE_BOTH:
        docs_res = await _run_docs_subroute()
        sql_res = await _run_sql_subroute()
        chunks = docs_res[0]
        sql_contexts = sql_res[1]
        iterations = docs_res[2] + sql_res[2]
        verdicts = docs_res[3] + sql_res[3]

    # Sufficiency has two sources: the docs grader's verdict (docs/both) and,
    # for the SQL route (which has no grader), whether any query returned data.
    # If either side produced an answer, don't abstain.
    graded_sufficient = any(v.sufficient for v in verdicts)
    sufficient = graded_sufficient or bool(sql_contexts)
    if verdicts:
        await _emit("grade", sufficient=sufficient)

    # --- Abstain decision (normal never abstains) ---
    abstain_reason: str | None = None
    if (decision.route != ROUTE_NORMAL
            and pipeline.abstain_when_insufficient and not sufficient):
        abstain_reason = (
            verdicts[-1].abstain_reason if verdicts and verdicts[-1].abstain_reason
            else "The available knowledge did not contain enough to answer."
        )

    # --- Synthesize ---
    if abstain_reason is not None:
        assistant_content = f"I don't know: {abstain_reason}"
        citations: list[Citation] = []
        await _emit("synthesize", chars=0, abstained=True)
    else:
        ans_llm, ans_url, ans_key = await _open(ans_sel)
        assistant_content, citations = await synthesize_answer(
            llm=ans_llm, base_url=ans_url, api_key=ans_key,
            model_id=ans_sel.model_id, generation=pipeline.generation,
            route=decision.route, system_prompt=base_system_prompt,
            user_message=user_message, chunks=chunks, sql_contexts=sql_contexts,
        )
        await _emit("synthesize", chars=len(assistant_content))

    trace = RoutingTrace(
        route=decision.route, rationale=decision.rationale,
        attempts=iterations, verdicts=verdicts,
    )
    metadata = {"routing": trace.to_dict()}

    # --- Step 7: persist assistant message + bump activity ---
    if persist:
        message_id = await append_message(
            session_repo=session_repo,
            message_repo=message_repo,
            session_id=session_id,
            role="assistant",
            content=assistant_content,
            citations=[c.to_dict() for c in citations],
            metadata=metadata,
        )
    else:
        from uuid import uuid4 as _uuid4
        message_id = _uuid4()

    if persist:
        await touch_session(session_repo=session_repo, session_id=session_id)

    return AnswerView(
        session_id=session_id,
        message_id=message_id,
        content=assistant_content,
        citations=citations,
        iterations=iterations,
        retrieved_contexts=[c.content for c in chunks] + sql_contexts,
        routing_trace=trace.to_dict(),
        prompt_tokens=meter.prompt_tokens,
        completion_tokens=meter.completion_tokens,
    )
