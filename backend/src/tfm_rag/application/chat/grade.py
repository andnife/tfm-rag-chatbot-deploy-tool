from typing import Any, Protocol

from tfm_rag.domain.catalog.evaluator_schemas import (
    GRADE_VERDICT_TOOL,
    STRUCTURED_OUTPUT_MIN_TOKENS,
    build_grade_verdict_schema,
)
from tfm_rag.domain.catalog.routes import ROUTE_SQL
from tfm_rag.domain.value_objects.grade_verdict import GradeVerdict
from tfm_rag.domain.value_objects.pipeline_config import GenerationConfig
from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMResponse,
    LLMToolCall,
)


class _LLM(Protocol):
    async def generate(self, **kwargs: Any) -> LLMResponse: ...


_GRADE_SYSTEM = (
    "You are a strict grader. Call the `grade_verdict` tool exactly once. "
    "The tool argument MUST be a boolean field named `sufficient`: set it to "
    "true if the CONTEXT contains enough information to answer the QUESTION, "
    "false otherwise. Do NOT pass the question or the context back as "
    "arguments. Do not answer the question yourself."
)

# SQL results are terse by nature (a scalar, a COUNT, a few rows). The generic
# "strict grader" above rejected valid SQL results as insufficient, forcing the
# pipeline to abstain despite having the answer. This route-specific prompt tells
# the grader that a terse result IS an answer.
_GRADE_SYSTEM_SQL = (
    "You are grading whether a SQL query RESULT answers a question. Call the "
    "`grade_verdict` tool exactly once with a boolean field named `sufficient`. "
    "The CONTEXT is a SQL result table. Set sufficient=true when it contains the "
    "data that answers the QUESTION — a single value, a count, or a few rows IS "
    "enough; do NOT require extra prose, explanation or additional columns. Set "
    "sufficient=false ONLY if the result is an execution error, is empty when the "
    "question needs matching rows, or its columns are unrelated to the question. "
    "Do NOT pass the question or the context back as arguments. Do not answer the "
    "question yourself."
)


def _parse(resp: LLMResponse) -> GradeVerdict | None:
    if not isinstance(resp, LLMToolCall) or resp.tool != GRADE_VERDICT_TOOL:
        return None
    if "sufficient" not in resp.arguments:
        return None
    return GradeVerdict.from_dict(resp.arguments)


async def grade_context(
    *,
    llm: _LLM,
    base_url: str,
    api_key: str | None,
    model_id: str,
    generation: GenerationConfig,
    route: str,
    user_message: str,
    context_text: str,
    can_reformulate: bool,
) -> GradeVerdict:
    """Judge whether `context_text` answers `user_message`. One attempt + one
    reprompt; on failure a defensive `sufficient=False` verdict."""
    if can_reformulate:
        hint = (
            "If it is NOT sufficient, also provide a `fixed_sql` (a corrected "
            "SELECT)." if route == ROUTE_SQL else
            "If it is NOT sufficient, also provide a `reformulated_query` (a "
            "better search query)."
        )
    else:
        hint = "Only report `sufficient` (no retries remain)."
    system = _GRADE_SYSTEM_SQL if route == ROUTE_SQL else _GRADE_SYSTEM
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user",
         "content": (
             f"QUESTION: {user_message}\n\nCONTEXT:\n{context_text}\n\n{hint}"
         )},
    ]
    tools = build_grade_verdict_schema()

    for _attempt in range(2):
        resp = await llm.generate(
            base_url=base_url, api_key=api_key, model_id=model_id,
            messages=messages, tools=tools,
            temperature=generation.temperature, top_p=generation.top_p,
            max_tokens=max(generation.max_tokens, STRUCTURED_OUTPUT_MIN_TOKENS),
        )
        verdict = _parse(resp)
        if verdict is not None:
            return verdict
        messages.append({
            "role": "user",
            "content": (
                f"Invalid response. Call the {GRADE_VERDICT_TOOL} tool with a "
                "single boolean argument named `sufficient` (true/false). Do "
                "not include the question or context as arguments."
            ),
        })

    return GradeVerdict(
        sufficient=False, abstain_reason="grader returned no valid verdict"
    )
