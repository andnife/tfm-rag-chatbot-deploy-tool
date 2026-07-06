"""One turn of the sql_generator's conversational thread.

The SQL sub-route is a single growing message thread: the schema is in the
system message ONCE, then the model runs `run_query` calls whose results are fed
back as turns, until it has enough data and self-terminates by replying with
plain text. There is no explore/answer distinction and no separate grader — the
model itself decides when to stop; the answer_generator then synthesizes the
final reply (with the chatbot's persona) from the accumulated results.
"""
from typing import Any, Literal, Protocol
from uuid import UUID

from tfm_rag.domain.catalog.evaluator_schemas import (
    RUN_QUERY_TOOL,
    STRUCTURED_OUTPUT_MIN_TOKENS,
    build_run_query_schema,
)
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.pipeline_config import GenerationConfig
from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMResponse,
    LLMTextResponse,
    LLMToolCall,
)
from tfm_rag.domain.value_objects.sql_plan import SqlPlan


class _LLM(Protocol):
    async def generate(self, **kwargs: Any) -> LLMResponse: ...


_SQL_SYSTEM = (
    "You answer questions by querying SQL databases. Use the `run_query` tool to "
    "run ONE read-only SELECT at a time; its result is returned to you. Query as "
    "many times as needed — e.g. first SELECT DISTINCT a text column to learn its "
    "real stored values before filtering (never assume a value's spelling or "
    "language; the data may store 'Europa', not 'Europe'). When you have gathered "
    "enough data to answer, STOP: reply with a one-line plain-text confirmation "
    "instead of calling the tool. Only SELECT — never modify data."
)


def build_initial_sql_messages(
    *, schema_context: str, user_message: str, allowed_source_ids: tuple[UUID, ...],
) -> list[dict[str, Any]]:
    """The opening thread: system (instruction + schema once) + the question."""
    allowed = ", ".join(str(s) for s in allowed_source_ids)
    return [
        {"role": "system",
         "content": f"{_SQL_SYSTEM}\n\nDatabase schema:\n{schema_context}"},
        {"role": "user",
         "content": f"Allowed source ids: {allowed}\n\nQuestion: {user_message}"},
    ]


def _parse(resp: LLMResponse, *, allowed: tuple[UUID, ...]) -> SqlPlan | None:
    if not isinstance(resp, LLMToolCall) or resp.tool != RUN_QUERY_TOOL:
        return None
    raw_id = str(resp.arguments.get("source_id", ""))
    try:
        source_id = UUID(raw_id)
    except (ValueError, AttributeError):
        return None
    if source_id not in allowed:
        return None
    try:
        return SqlPlan(source_id=source_id, sql=str(resp.arguments.get("sql", "")))
    except ValidationError:
        return None


async def request_next_query(
    *,
    llm: _LLM,
    base_url: str,
    api_key: str | None,
    model_id: str,
    generation: GenerationConfig,
    messages: list[dict[str, Any]],
    allowed_source_ids: tuple[UUID, ...],
) -> tuple[Literal["query", "done"], SqlPlan | None]:
    """Run ONE turn of the SQL thread. Returns:
      - ("query", SqlPlan): the model wants to run this query next.
      - ("done", None): the model self-terminated (plain-text reply) — or, after
        a corrective reprompt, still gave nothing runnable. Either way the caller
        stops querying and synthesizes from whatever results it has.

    Appends any corrective reprompt to `messages` in place. The caller is
    responsible for appending the executed query + its result to the thread.
    """
    tools = build_run_query_schema()
    allowed_str = ", ".join(str(s) for s in allowed_source_ids)
    for _attempt in range(2):
        resp = await llm.generate(
            base_url=base_url, api_key=api_key, model_id=model_id,
            messages=messages, tools=tools,
            temperature=generation.temperature, top_p=generation.top_p,
            max_tokens=max(generation.max_tokens, STRUCTURED_OUTPUT_MIN_TOKENS),
        )
        if isinstance(resp, LLMTextResponse):
            return ("done", None)  # self-terminated: it has enough (or nothing)
        plan = _parse(resp, allowed=allowed_source_ids)
        if plan is not None:
            return ("query", plan)
        messages.append({
            "role": "user",
            "content": (
                f"Invalid response. Call the {RUN_QUERY_TOOL} tool with a "
                f"`source_id` from [{allowed_str}] and a single SELECT `sql`, or "
                "reply with plain text if you already have enough data to answer."
            ),
        })
    return ("done", None)
