import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.chat.append_message import append_message as _real_append_message
from tfm_rag.application.chat.create_session import create_session as _real_create_session
from tfm_rag.application.chat.query_database import (
    QueryDatabaseInput,
)
from tfm_rag.application.chat.query_database import (
    query_database as _real_query_database,
)
from tfm_rag.application.chat.retrieve_docs import retrieve_docs as _real_retrieve_docs
from tfm_rag.application.chat.system_prompt import build_chatbot_system_prompt
from tfm_rag.application.chat.touch_session import touch_session as _real_touch_session
from tfm_rag.domain.catalog.agent_tools import (
    TOOL_ABSTAIN,
    TOOL_FINAL_ANSWER,
    TOOL_QUERY_DATABASE,
    TOOL_SEARCH_DOCS,
    build_tool_schemas,
)
from tfm_rag.domain.errors.chat import (
    DatabaseSourceMismatchError,
    QueryExecutionError,
    UnsafeSQLError,
)
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import DatabaseConnectionError
from tfm_rag.domain.value_objects.citation import Citation
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMTextResponse,
    LLMToolCall,
    RetrievalIteration,
)
from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk
from tfm_rag.infrastructure.database_connectors import DATABASE_CONNECTORS
from tfm_rag.infrastructure.embedders.dispatcher import EmbedderDispatcher
from tfm_rag.infrastructure.llm_providers.dispatcher import LLMDispatcher
from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
    ChatbotRepository,
)
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repositories.sources_repo import (
    SourceRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.secrets.fernet_encryptor import (
    FernetSecretEncryptor,
)
from tfm_rag.infrastructure.settings import Settings
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore

_log = logging.getLogger(__name__)

ChatbotRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatbotRepository
]
KbRepoFactory = Callable[
    [AsyncSession, RequestContext], KnowledgeBaseRepository
]

RetrieveDocs = Callable[..., Awaitable[list[RetrievedChunk]]]
CreateSession = Callable[..., Awaitable[UUID]]
AppendMessage = Callable[..., Awaitable[UUID]]
TouchSession = Callable[..., Awaitable[None]]
SourcesRepoFactory = Callable[[AsyncSession], SourceRepository]


def _default_chatbot_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatbotRepository:
    return ChatbotRepository(session, ctx)


def _default_kb_repo(
    session: AsyncSession, ctx: RequestContext
) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session, ctx)


def _default_sources_repo(session: AsyncSession) -> SourceRepository:
    return SourceRepository(session)


QueryDatabaseFn = Callable[..., Awaitable[Any]]


def _default_query_database(
    session: AsyncSession,
    *,
    settings: Settings,
    allowed_kb_ids: tuple[UUID, ...],
    source_id: UUID,
    sql: str,
    row_limit: int,
) -> Awaitable[Any]:
    sources_repo = SourceRepository(session)
    return _real_query_database(
        QueryDatabaseInput(
            allowed_kb_ids=allowed_kb_ids,
            source_id=source_id,
            sql=sql,
            row_limit=row_limit,
        ),
        sources_repo=sources_repo,  # type: ignore[arg-type]
        connectors=DATABASE_CONNECTORS,
        encryptor=FernetSecretEncryptor(settings.fernet_key),
    )


@dataclass(frozen=True, slots=True)
class AnswerView:
    session_id: UUID
    message_id: UUID
    content: str
    citations: list[Citation]
    iterations: list[RetrievalIteration]
    retrieved_contexts: list[str] = field(default_factory=list, hash=False)


_SYSTEM_META_PROMPT = (
    "You have access to a knowledge base via the `search_docs` tool. "
    "Use it to ground your answer in the user's documents before "
    "responding with `final_answer`. If after a search you do not have "
    "the information needed, call `abstain` with a short reason rather "
    "than guessing."
)


def _build_system_message(chatbot_system_prompt: str) -> dict[str, Any]:
    parts = [chatbot_system_prompt.strip(), _SYSTEM_META_PROMPT]
    return {"role": "system", "content": "\n\n".join(p for p in parts if p)}


def _format_chunks_for_tool_result(chunks: list[RetrievedChunk]) -> str:
    """Render retrieved chunks as a single string the LLM can read as the
    tool result. We include filename + a short excerpt per chunk.
    """
    if not chunks:
        return "(no relevant documents found)"
    lines: list[str] = []
    for i, c in enumerate(chunks):
        body = c.content.strip().replace("\n", " ")
        if len(body) > 600:
            body = body[:600].rstrip() + "..."
        lines.append(f"[{i}] {c.source_filename}: {body}")
    return "\n".join(lines)


async def answer_query(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    chatbot_repo_factory: ChatbotRepoFactory = _default_chatbot_repo,
    kb_repo_factory: KbRepoFactory = _default_kb_repo,
    sources_repo_factory: SourcesRepoFactory = _default_sources_repo,
    llm_dispatcher: LLMDispatcher,
    retrieve_docs: RetrieveDocs = _real_retrieve_docs,
    create_session: CreateSession = _real_create_session,
    append_message: AppendMessage = _real_append_message,
    touch_session: TouchSession = _real_touch_session,
    query_database_fn: QueryDatabaseFn = _default_query_database,
    qdrant: QdrantStore,
    embedder_dispatcher: EmbedderDispatcher,
    settings: Settings,
    chatbot_id: UUID,
    session_id: UUID | None,
    user_message: str,
    persist: bool = True,
    session_origin: Literal["playground", "widget"] = "playground",
    public_session_cookie: str | None = None,
) -> AnswerView:
    """Agent-loop use case: answers `user_message` for `chatbot_id`,
    persisting both user + assistant turns to the session.

    Workflow:
      1. Load chatbot (tenant-scoped). Build LLMSelection + PipelineConfig.
      2. If no session_id, create a playground session.
      3. Append user message.
      4. Loop up to `max_retrieval_iterations`: ask LLM for a tool call.
         - `search_docs` → run retrieve_docs, accumulate chunks, append
           tool message to LLM context, loop.
         - `final_answer` → break with answer.
         - `abstain` → break with abstain reason as content.
         - text response → treat as implicit final_answer.
         - unknown tool → raise.
      5. If loop exhausted without a terminal decision, synthesise an
         abstain ("max iterations reached").
      6. Append assistant message with citations + iterations metadata.
      7. Touch the session.
    """
    # --- Step 1: load chatbot ---
    chatbot_repo = chatbot_repo_factory(session, ctx)
    try:
        row = await chatbot_repo.get(chatbot_id)
    except NotFoundError as exc:
        raise ChatbotNotFoundError(str(exc)) from exc
    kb_ids = await chatbot_repo.list_kb_ids(chatbot_id)

    llm_selection = LLMSelection.from_dict(row.llm_selection)
    pipeline = PipelineConfig.from_dict(row.pipeline_config)

    # Load the chatbot's KB source rows so we can include DB schemas in the
    # system prompt. Only `type='database'` entries contribute.
    all_sources: list[dict[str, Any]] = []
    sources_repo = sources_repo_factory(session)
    for kb_id in kb_ids:
        rows = await sources_repo.list_by_kb(kb_id)
        for src_row in rows:
            all_sources.append({
                "source_id": src_row.id,
                "type": src_row.type,
                "payload": dict(src_row.payload or {}),
            })
    has_db_sources = any(s["type"] == "database" for s in all_sources)

    base_system_prompt = row.system_prompt or ""
    final_system_prompt = build_chatbot_system_prompt(
        base_system_prompt, db_sources=all_sources,
    )

    # --- Step 2: ensure a session exists ---
    if session_id is None:
        if persist:
            session_id = await create_session(
                session, ctx,
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
            session, ctx,
            session_id=session_id,
            role="user",
            content=user_message,
            citations=None,
            metadata=None,
        )

    # --- Step 4: the agent loop ---
    llm = llm_dispatcher.for_provider(llm_selection.provider_id)
    base_url = settings.ollama_base_url
    api_key: str | None = None

    messages: list[dict[str, Any]] = [
        _build_system_message(final_system_prompt),
        {"role": "user", "content": user_message},
    ]
    tools = build_tool_schemas(include_query_database=has_db_sources)

    seen_chunks: dict[str, RetrievedChunk] = {}
    iterations: list[RetrievalIteration] = []

    final_answer_text: str | None = None
    abstain_reason: str | None = None

    for i in range(pipeline.max_retrieval_iterations):
        t0 = time.perf_counter()
        resp = await llm.generate(
            base_url=base_url,
            api_key=api_key,
            model_id=llm_selection.model_id,
            messages=messages,
            tools=tools,
            temperature=pipeline.generation.temperature,
            top_p=pipeline.generation.top_p,
            max_tokens=pipeline.generation.max_tokens,
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0

        if isinstance(resp, LLMTextResponse):
            final_answer_text = resp.text
            iterations.append(RetrievalIteration(
                index=i, tool=TOOL_FINAL_ANSWER,
                query=None, num_chunks=None, latency_ms=latency_ms,
            ))
            break

        if not isinstance(resp, LLMToolCall):  # pragma: no cover — exhaustiveness
            raise RuntimeError(f"Unexpected LLM response type: {type(resp).__name__}")

        if resp.tool == TOOL_FINAL_ANSWER:
            final_answer_text = str(resp.arguments.get("answer", ""))
            iterations.append(RetrievalIteration(
                index=i, tool=TOOL_FINAL_ANSWER,
                query=None, num_chunks=None, latency_ms=latency_ms,
            ))
            break

        if resp.tool == TOOL_ABSTAIN:
            abstain_reason = str(resp.arguments.get("reason", "no reason given"))
            iterations.append(RetrievalIteration(
                index=i, tool=TOOL_ABSTAIN,
                query=None, num_chunks=None, latency_ms=latency_ms,
            ))
            break

        if resp.tool == TOOL_SEARCH_DOCS:
            query = str(resp.arguments.get("query", "")).strip()
            chunks = await retrieve_docs(
                session, ctx,
                qdrant=qdrant,
                dispatcher=embedder_dispatcher,
                settings=settings,
                kb_ids=kb_ids,
                query=query,
                top_k=pipeline.top_k,
                score_threshold=(
                    pipeline.score_threshold
                    if pipeline.score_threshold > 0.0
                    else None
                ),
            )
            for c in chunks:
                seen_chunks.setdefault(c.point_id, c)
            iterations.append(RetrievalIteration(
                index=i, tool=TOOL_SEARCH_DOCS,
                query=query, num_chunks=len(chunks), latency_ms=latency_ms,
            ))
            messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {"name": TOOL_SEARCH_DOCS, "arguments": resp.arguments},
                }],
            })
            messages.append({
                "role": "tool",
                "name": TOOL_SEARCH_DOCS,
                "content": _format_chunks_for_tool_result(chunks),
            })
            continue

        elif resp.tool == TOOL_QUERY_DATABASE:
            args = resp.arguments
            raw_source_id = args.get("source_id")
            raw_sql = args.get("sql")
            if not isinstance(raw_source_id, str) or not isinstance(raw_sql, str):
                # Treat as abstain — model emitted malformed args.
                final_answer_text = "I tried to query a database but the request was malformed."
                iterations.append(RetrievalIteration(
                    index=i, tool=TOOL_QUERY_DATABASE,
                    query=None, num_chunks=None, latency_ms=0.0,
                    sql=None, row_count=None,
                ))
                break
            t0_db = time.perf_counter()
            try:
                source_uuid = UUID(raw_source_id)
            except ValueError:
                # Malformed UUID; feed the model an error so it can recover.
                iterations.append(RetrievalIteration(
                    index=i, tool=TOOL_QUERY_DATABASE,
                    query=None, num_chunks=None, latency_ms=0.0,
                    sql=raw_sql, row_count=None,
                ))
                messages.append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "function": {"name": TOOL_QUERY_DATABASE, "arguments": args},
                    }],
                })
                messages.append({
                    "role": "tool",
                    "name": TOOL_QUERY_DATABASE,
                    "content": f"error: source_id {raw_source_id!r} is not a valid UUID",
                })
                continue
            try:
                out = await query_database_fn(
                    session,
                    settings=settings,
                    allowed_kb_ids=tuple(kb_ids),
                    source_id=source_uuid,
                    sql=raw_sql,
                    row_limit=50,
                )
                tool_response_text = out.result.to_markdown()
                iterations.append(RetrievalIteration(
                    index=i, tool=TOOL_QUERY_DATABASE,
                    query=None, num_chunks=None,
                    latency_ms=(time.perf_counter() - t0_db) * 1000.0,
                    sql=raw_sql, row_count=out.result.row_count,
                ))
            except (UnsafeSQLError, DatabaseSourceMismatchError,
                    QueryExecutionError, DatabaseConnectionError) as exc:
                tool_response_text = f"error: {exc}"
                iterations.append(RetrievalIteration(
                    index=i, tool=TOOL_QUERY_DATABASE,
                    query=None, num_chunks=None,
                    latency_ms=(time.perf_counter() - t0_db) * 1000.0,
                    sql=raw_sql, row_count=0,
                ))
            messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {"name": TOOL_QUERY_DATABASE, "arguments": args},
                }],
            })
            messages.append({
                "role": "tool",
                "name": TOOL_QUERY_DATABASE,
                "content": tool_response_text,
            })
            continue

        # Unknown tool — defensive: synthesise an abstain rather than crash.
        _log.warning(
            "answer_query: unknown tool %r returned by LLM; aborting loop",
            resp.tool,
        )
        abstain_reason = f"LLM requested unknown tool {resp.tool!r}"
        iterations.append(RetrievalIteration(
            index=i, tool=TOOL_ABSTAIN,
            query=None, num_chunks=None, latency_ms=latency_ms,
        ))
        break

    # --- Step 5: handle loop exhaustion ---
    if final_answer_text is None and abstain_reason is None:
        abstain_reason = (
            "Reached max iterations without a final answer. The chatbot "
            "couldn't ground a confident response in the knowledge base."
        )
        iterations.append(RetrievalIteration(
            index=len(iterations), tool=TOOL_ABSTAIN,
            query=None, num_chunks=None, latency_ms=0.0,
        ))

    # --- Step 6: prepare assistant message ---
    if final_answer_text is not None:
        assistant_content = final_answer_text
        citations = [Citation.from_chunk(c) for c in seen_chunks.values()]
    else:
        assert abstain_reason is not None
        assistant_content = f"I don't know: {abstain_reason}"
        citations = []

    metadata = {"iterations": [it.to_dict() for it in iterations]}
    if persist:
        message_id = await append_message(
            session, ctx,
            session_id=session_id,
            role="assistant",
            content=assistant_content,
            citations=[c.to_dict() for c in citations],
            metadata=metadata,
        )
    else:
        from uuid import uuid4 as _uuid4
        message_id = _uuid4()

    # --- Step 7: bump activity ---
    if persist:
        await touch_session(session, ctx, session_id=session_id)

    return AnswerView(
        session_id=session_id,
        message_id=message_id,
        content=assistant_content,
        citations=citations,
        iterations=iterations,
        retrieved_contexts=[c.content for c in seen_chunks.values()],
    )
