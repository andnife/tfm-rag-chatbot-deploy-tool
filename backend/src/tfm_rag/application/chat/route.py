from typing import Any, Protocol

from tfm_rag.domain.catalog.evaluator_schemas import (
    ROUTE_DECISION_TOOL,
    STRUCTURED_OUTPUT_MIN_TOKENS,
    build_route_decision_schema,
)
from tfm_rag.domain.catalog.routes import ROUTE_DOCS, ROUTE_NAMES, ROUTE_NORMAL
from tfm_rag.domain.value_objects.pipeline_config import GenerationConfig
from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMResponse,
    LLMToolCall,
)
from tfm_rag.domain.value_objects.route_decision import RouteDecision


class _LLM(Protocol):
    async def generate(self, **kwargs: Any) -> LLMResponse: ...


_ROUTE_SYSTEM = (
    "You are a routing classifier. Call the `route_decision` tool exactly once. "
    "Its arguments MUST be a string field named `route` (one of the allowed "
    "route values) and a short `rationale`. Do NOT pass the question or the "
    "knowledge back as arguments. Do not answer the question yourself."
)

# Only added when SQL is available. Without an explicit criterion the classifier
# almost never picked `both` for compound questions (0.05 in the 180-run); it
# latched onto a single intent. Spell out when each route — especially `both` —
# applies.
_ROUTE_SQL_GUIDANCE = (
    " Guidance on the route value: use `docs` when the answer is in the "
    "documents; use `sql` when it needs live data from the database (counts, "
    "lookups, aggregations); use `both` when a SINGLE question needs BOTH at "
    "once — e.g. one part is a fact from the documents and another part needs a "
    "figure from the database. If the question has two sub-parts pulling from "
    "different sources, choose `both`."
)


def _parse(resp: LLMResponse, *, allowed: tuple[str, ...]) -> RouteDecision | None:
    if not isinstance(resp, LLMToolCall) or resp.tool != ROUTE_DECISION_TOOL:
        return None
    route = str(resp.arguments.get("route", ""))
    if route not in allowed:
        return None
    return RouteDecision(
        route=route,
        rationale=str(resp.arguments.get("rationale", "")),
        raw=dict(resp.arguments),
    )


async def evaluate_route(
    *,
    llm: _LLM,
    base_url: str,
    api_key: str | None,
    model_id: str,
    generation: GenerationConfig,
    user_message: str,
    routing_context: str,
    allow_sql: bool,
) -> RouteDecision:
    """Classify `user_message` into a route. One attempt + one reprompt; then
    a defensive fallback (docs if the context exposes documents, else normal).
    """
    allowed = ROUTE_NAMES if allow_sql else (ROUTE_NORMAL, ROUTE_DOCS)
    tools = build_route_decision_schema(allow_sql=allow_sql)
    system = _ROUTE_SYSTEM + (_ROUTE_SQL_GUIDANCE if allow_sql else "")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user",
         "content": f"Available knowledge:\n{routing_context}\n\nQuestion: {user_message}"},
    ]

    for _attempt in range(2):
        resp = await llm.generate(
            base_url=base_url, api_key=api_key, model_id=model_id,
            messages=messages, tools=tools,
            temperature=generation.temperature, top_p=generation.top_p,
            max_tokens=max(generation.max_tokens, STRUCTURED_OUTPUT_MIN_TOKENS),
        )
        decision = _parse(resp, allowed=allowed)
        if decision is not None:
            return decision
        messages.append({
            "role": "user",
            "content": (
                f"Invalid response. Call the {ROUTE_DECISION_TOOL} tool with a "
                f"`route` field equal to one of: {', '.join(allowed)}."
            ),
        })

    fallback = ROUTE_DOCS if routing_context.strip() else ROUTE_NORMAL
    return RouteDecision(
        route=fallback, rationale="fallback: evaluator gave no valid route",
        raw={},
    )
