from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMTextResponse,
    LLMToolCall,
    TokenUsage,
)


def test_token_usage_add_and_total() -> None:
    a = TokenUsage(prompt_tokens=10, completion_tokens=4)
    b = TokenUsage(prompt_tokens=3, completion_tokens=1)
    s = a + b
    assert s.prompt_tokens == 13
    assert s.completion_tokens == 5
    assert s.total_tokens == 18


def test_response_vos_default_usage_none_and_accept_usage() -> None:
    # Existing positional construction still works (usage defaults to None).
    tc = LLMToolCall(tool="route", arguments={"x": 1})
    txt = LLMTextResponse(text="hi")
    assert tc.usage is None and txt.usage is None
    tc2 = LLMToolCall(tool="route", arguments={}, usage=TokenUsage(5, 2))
    assert tc2.usage.total_tokens == 7
