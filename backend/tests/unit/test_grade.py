import pytest

from tfm_rag.application.chat.grade import grade_context
from tfm_rag.domain.catalog.evaluator_schemas import (
    GRADE_VERDICT_TOOL,
    STRUCTURED_OUTPUT_MIN_TOKENS,
)
from tfm_rag.domain.catalog.routes import ROUTE_DOCS, ROUTE_SQL
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
async def test_grade_sufficient() -> None:
    llm = _FakeLLM(LLMToolCall(tool=GRADE_VERDICT_TOOL,
                               arguments={"sufficient": True}))
    v = await grade_context(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=_gen(), route=ROUTE_DOCS, user_message="q",
        context_text="relevant text", can_reformulate=True,
    )
    assert v.sufficient is True
    tools = llm.calls[0]["tools"]
    assert [t["function"]["name"] for t in tools] == [GRADE_VERDICT_TOOL]


@pytest.mark.asyncio
async def test_grade_sql_route_uses_result_aware_prompt() -> None:
    """On the SQL route a terse result (a count / single value) must count as
    sufficient — the grader prompt must tell the judge so, instead of the
    doc-oriented 'strict grader' prompt that rejected valid SQL results."""
    llm = _FakeLLM(LLMToolCall(tool=GRADE_VERDICT_TOOL,
                               arguments={"sufficient": True}))
    await grade_context(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=_gen(), route=ROUTE_SQL, user_message="how many?",
        context_text="| COUNT(*) |\n| 6 |", can_reformulate=False,
    )
    system = llm.calls[0]["messages"][0]["content"].lower()
    assert "single" in system and "count" in system
    assert "strict" not in system


@pytest.mark.asyncio
async def test_grade_docs_route_keeps_strict_prompt() -> None:
    """The document route keeps the original strict grader prompt."""
    llm = _FakeLLM(LLMToolCall(tool=GRADE_VERDICT_TOOL,
                               arguments={"sufficient": True}))
    await grade_context(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=_gen(), route=ROUTE_DOCS, user_message="q",
        context_text="text", can_reformulate=False,
    )
    system = llm.calls[0]["messages"][0]["content"].lower()
    assert "strict" in system


@pytest.mark.asyncio
async def test_grade_floors_max_tokens_for_tool_call() -> None:
    """A small answer max_tokens must not starve the forced grade tool-call."""
    llm = _FakeLLM(LLMToolCall(tool=GRADE_VERDICT_TOOL, arguments={"sufficient": True}))
    await grade_context(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=GenerationConfig(max_tokens=32), route=ROUTE_DOCS,
        user_message="q", context_text="ctx", can_reformulate=False,
    )
    assert llm.calls[0]["max_tokens"] == STRUCTURED_OUTPUT_MIN_TOKENS


@pytest.mark.asyncio
async def test_grade_insufficient_with_reformulation() -> None:
    llm = _FakeLLM(LLMToolCall(
        tool=GRADE_VERDICT_TOOL,
        arguments={"sufficient": False, "reformulated_query": "better q"},
    ))
    v = await grade_context(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=_gen(), route=ROUTE_DOCS, user_message="q",
        context_text="(no relevant documents found)", can_reformulate=True,
    )
    assert v.sufficient is False
    assert v.reformulated_query == "better q"


@pytest.mark.asyncio
async def test_grade_reprompts_then_falls_back() -> None:
    llm = _FakeLLM(LLMTextResponse(text="hmm"), LLMTextResponse(text="still text"))
    v = await grade_context(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=_gen(), route=ROUTE_DOCS, user_message="q",
        context_text="text", can_reformulate=True,
    )
    assert v.sufficient is False
    assert v.abstain_reason == "grader returned no valid verdict"
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_grade_prompt_steers_model_to_sufficient_field() -> None:
    """The prompt must explicitly instruct emitting the boolean `sufficient`.

    Regression: llama3.1 via Ollama otherwise echoes the prompt labels back as
    tool arguments (`{context, question}`) instead of `sufficient`, so the
    verdict never parses and the pipeline abstains with "no valid verdict".
    """
    llm = _FakeLLM(LLMToolCall(tool=GRADE_VERDICT_TOOL, arguments={"sufficient": True}))
    await grade_context(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=_gen(), route=ROUTE_DOCS, user_message="q",
        context_text="text", can_reformulate=True,
    )
    # The SYSTEM message itself must name the required `sufficient` argument and
    # tell the model not to echo the question/context back as arguments — the
    # incidental "NOT sufficient" in the hint is not enough to steer llama3.1.
    sys_msg = str(llm.calls[0]["messages"][0]["content"]).lower()
    assert "sufficient" in sys_msg
    assert "argument" in sys_msg


@pytest.mark.asyncio
async def test_grade_recovers_when_reprompt_returns_valid_verdict() -> None:
    """A first tool-call with the wrong args (no `sufficient`) is rejected, and
    the reprompt recovers a valid verdict on the second attempt."""
    llm = _FakeLLM(
        LLMToolCall(tool=GRADE_VERDICT_TOOL,
                    arguments={"context": "x", "question": "q"}),
        LLMToolCall(tool=GRADE_VERDICT_TOOL, arguments={"sufficient": True}),
    )
    v = await grade_context(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=_gen(), route=ROUTE_DOCS, user_message="q",
        context_text="text", can_reformulate=True,
    )
    assert v.sufficient is True
    assert len(llm.calls) == 2
    # The reprompt must also name the `sufficient` field explicitly.
    reprompt = str(llm.calls[1]["messages"][-1]["content"]).lower()
    assert "sufficient" in reprompt
