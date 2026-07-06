import pytest

from tfm_rag.application.chat.route import evaluate_route
from tfm_rag.domain.catalog.evaluator_schemas import ROUTE_DECISION_TOOL
from tfm_rag.domain.catalog.routes import ROUTE_DOCS, ROUTE_NORMAL
from tfm_rag.domain.value_objects.pipeline_config import GenerationConfig
from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMTextResponse,
    LLMToolCall,
)


class _FakeLLM:
    def __init__(self, *responses: object) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def generate(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self._responses.pop(0)


def _gen() -> GenerationConfig:
    return GenerationConfig()


@pytest.mark.asyncio
async def test_route_returns_tool_decision() -> None:
    llm = _FakeLLM(LLMToolCall(tool=ROUTE_DECISION_TOOL,
                               arguments={"route": ROUTE_DOCS, "rationale": "factual"}))
    decision = await evaluate_route(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=_gen(), user_message="what is X?",
        routing_context="KB: handbook", allow_sql=False,
    )
    assert decision.route == ROUTE_DOCS
    assert decision.rationale == "factual"
    # Single tool offered, named route_decision.
    tools = llm.calls[0]["tools"]
    assert [t["function"]["name"] for t in tools] == [ROUTE_DECISION_TOOL]


@pytest.mark.asyncio
async def test_route_prompt_guides_both_when_sql_allowed() -> None:
    """Compound questions need the `both` route, but the router almost never
    picked it (0.05 in the 180-run) because the prompt gave no criterion.
    When SQL is allowed the system prompt must explain when to choose `both`."""
    llm = _FakeLLM(LLMToolCall(tool=ROUTE_DECISION_TOOL,
                               arguments={"route": ROUTE_DOCS, "rationale": "x"}))
    await evaluate_route(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=_gen(), user_message="doc fact + db count?",
        routing_context="KB + DB", allow_sql=True,
    )
    system = llm.calls[0]["messages"][0]["content"].lower()
    assert "both" in system and "database" in system


@pytest.mark.asyncio
async def test_route_prompt_omits_sql_guidance_when_sql_disallowed() -> None:
    """With no SQL source, `sql`/`both` aren't options — the prompt must not
    mention them (it would only confuse a single-label classifier)."""
    llm = _FakeLLM(LLMToolCall(tool=ROUTE_DECISION_TOOL,
                               arguments={"route": ROUTE_DOCS, "rationale": "x"}))
    await evaluate_route(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=_gen(), user_message="q", routing_context="KB",
        allow_sql=False,
    )
    system = llm.calls[0]["messages"][0]["content"].lower()
    assert "both" not in system


@pytest.mark.asyncio
async def test_route_reprompts_then_succeeds_on_text_response() -> None:
    llm = _FakeLLM(
        LLMTextResponse(text="I think docs"),
        LLMToolCall(tool=ROUTE_DECISION_TOOL,
                    arguments={"route": ROUTE_NORMAL, "rationale": "greeting"}),
    )
    decision = await evaluate_route(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=_gen(), user_message="hi", routing_context="",
        allow_sql=False,
    )
    assert decision.route == ROUTE_NORMAL
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_route_falls_back_to_docs_when_invalid_twice() -> None:
    llm = _FakeLLM(
        LLMToolCall(tool=ROUTE_DECISION_TOOL, arguments={"route": "bogus"}),
        LLMTextResponse(text="still nonsense"),
    )
    decision = await evaluate_route(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=_gen(), user_message="?", routing_context="KB: handbook",
        allow_sql=False,
    )
    assert decision.route == ROUTE_DOCS  # context has docs


@pytest.mark.asyncio
async def test_route_falls_back_to_normal_without_docs() -> None:
    llm = _FakeLLM(
        LLMTextResponse(text="x"), LLMTextResponse(text="y"),
    )
    decision = await evaluate_route(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=_gen(), user_message="?", routing_context="",
        allow_sql=False,
    )
    assert decision.route == ROUTE_NORMAL


@pytest.mark.asyncio
async def test_route_prompt_steers_model_to_route_argument() -> None:
    """The SYSTEM prompt must name the `route` argument explicitly.

    Regression: llama3.1 via Ollama otherwise echoes the prompt labels back as
    tool arguments (`{question, knowledge}`) instead of `route`, so the
    decision never parses and routing silently falls back.
    """
    llm = _FakeLLM(LLMToolCall(tool=ROUTE_DECISION_TOOL,
                               arguments={"route": ROUTE_DOCS, "rationale": "x"}))
    await evaluate_route(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=_gen(), user_message="q", routing_context="KB: handbook",
        allow_sql=False,
    )
    sys_msg = str(llm.calls[0]["messages"][0]["content"]).lower()
    assert "route" in sys_msg
    assert "argument" in sys_msg
