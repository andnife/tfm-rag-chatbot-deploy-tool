from uuid import uuid4

import pytest

from tfm_rag.application.chat.generate_sql import (
    build_initial_sql_messages,
    request_next_query,
)
from tfm_rag.domain.catalog.evaluator_schemas import RUN_QUERY_TOOL
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


def test_initial_messages_carry_schema_once_and_question() -> None:
    sid = uuid4()
    msgs = build_initial_sql_messages(
        schema_context=f"Database source `{sid}` (mysql)",
        user_message="how many european countries?",
        allowed_source_ids=(sid,),
    )
    assert msgs[0]["role"] == "system"
    assert f"`{sid}`" in msgs[0]["content"]  # schema in the system message
    assert msgs[1]["role"] == "user"
    assert "how many european countries?" in msgs[1]["content"]
    assert str(sid) in msgs[1]["content"]  # allowed id surfaced


def test_system_prompt_mandates_exploration_and_self_termination() -> None:
    sid = uuid4()
    system = build_initial_sql_messages(
        schema_context="schema", user_message="q", allowed_source_ids=(sid,),
    )[0]["content"].lower()
    # Explore-before-filter guidance survives (the Europa/Europe footgun).
    assert "distinct" in system and "never assume" in system
    # Self-termination instruction: stop and reply with plain text.
    assert "plain-text" in system or "plain text" in system


@pytest.mark.asyncio
async def test_valid_tool_call_returns_query() -> None:
    sid = uuid4()
    llm = _FakeLLM(LLMToolCall(
        tool=RUN_QUERY_TOOL,
        arguments={"source_id": str(sid), "sql": "SELECT count(*) FROM users"},
    ))
    messages = build_initial_sql_messages(
        schema_context="s", user_message="q", allowed_source_ids=(sid,),
    )
    kind, plan = await request_next_query(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=_gen(), messages=messages, allowed_source_ids=(sid,),
    )
    assert kind == "query"
    assert plan is not None and plan.source_id == sid
    assert "SELECT" in plan.sql
    assert [t["function"]["name"] for t in llm.calls[0]["tools"]] == [RUN_QUERY_TOOL]


@pytest.mark.asyncio
async def test_text_response_is_self_termination() -> None:
    sid = uuid4()
    llm = _FakeLLM(LLMTextResponse(text="I have enough data."))
    kind, plan = await request_next_query(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=_gen(), messages=[], allowed_source_ids=(sid,),
    )
    assert kind == "done"
    assert plan is None
    assert len(llm.calls) == 1  # no reprompt on a clean text stop


@pytest.mark.asyncio
async def test_unknown_source_reprompts_then_stops() -> None:
    sid = uuid4()
    other = uuid4()
    llm = _FakeLLM(
        LLMToolCall(tool=RUN_QUERY_TOOL,
                    arguments={"source_id": str(other), "sql": "SELECT 1"}),
        LLMTextResponse(text="ok, stopping"),
    )
    messages = build_initial_sql_messages(
        schema_context="s", user_message="q", allowed_source_ids=(sid,),
    )
    kind, plan = await request_next_query(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=_gen(), messages=messages, allowed_source_ids=(sid,),
    )
    assert kind == "done" and plan is None
    assert len(llm.calls) == 2  # one reprompt after the invalid source_id
    # A corrective message was appended to the thread.
    assert any("Invalid response" in m.get("content", "") for m in messages)


@pytest.mark.asyncio
async def test_persistent_invalid_tool_calls_stop() -> None:
    sid = uuid4()
    other = uuid4()
    llm = _FakeLLM(
        LLMToolCall(tool=RUN_QUERY_TOOL,
                    arguments={"source_id": str(other), "sql": "SELECT 1"}),
        LLMToolCall(tool=RUN_QUERY_TOOL,
                    arguments={"source_id": str(other), "sql": "SELECT 2"}),
    )
    kind, plan = await request_next_query(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=_gen(), messages=[], allowed_source_ids=(sid,),
    )
    assert kind == "done" and plan is None
    assert len(llm.calls) == 2
