"""Unit tests for JudgeTokenCallback.

We test the callback in isolation — no real RAGAS, no real LLM.
We build a fake LLMResult-like object and call on_llm_end directly.
"""
from types import SimpleNamespace

from tfm_rag.infrastructure.evaluation.judge_token_callback import JudgeTokenCallback

# ---------------------------------------------------------------------------
# helpers to build fake LangChain LLMResult objects
# ---------------------------------------------------------------------------


def _make_result(llm_output: dict | None, generations: list | None = None):
    """Build a minimal fake LLMResult as SimpleNamespace."""
    gens = generations or []
    return SimpleNamespace(llm_output=llm_output, generations=gens)


def _gen(prompt_eval_count: int | None, eval_count: int | None):
    """Single generation with Ollama-style generation_info."""
    info: dict = {}
    if prompt_eval_count is not None:
        info["prompt_eval_count"] = prompt_eval_count
    if eval_count is not None:
        info["eval_count"] = eval_count
    g = SimpleNamespace(generation_info=info)
    return g


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_initial_counters_are_zero() -> None:
    cb = JudgeTokenCallback()
    assert cb.prompt_tokens == 0
    assert cb.completion_tokens == 0
    assert cb.calls == 0


def test_counts_calls_and_notifies_progress() -> None:
    """Each finished judge call increments `calls` and notifies `on_progress`
    with the running count — this drives the live scoring progress bar."""
    seen: list[int] = []
    cb = JudgeTokenCallback(on_progress=seen.append)
    r = _make_result(llm_output={"token_usage": {"prompt_tokens": 1, "completion_tokens": 1}})
    cb.on_llm_end(r)
    cb.on_llm_end(r)
    assert cb.calls == 2
    assert seen == [1, 2]


def test_reset_zeroes_call_count() -> None:
    cb = JudgeTokenCallback()
    cb.on_llm_end(_make_result(llm_output={}))
    assert cb.calls == 1
    cb.reset()
    assert cb.calls == 0


def test_openai_style_usage_accumulated() -> None:
    cb = JudgeTokenCallback()
    result = _make_result(
        llm_output={"token_usage": {"prompt_tokens": 50, "completion_tokens": 12}}
    )
    cb.on_llm_end(result)
    assert cb.prompt_tokens == 50
    assert cb.completion_tokens == 12


def test_openai_style_usage_accumulates_across_calls() -> None:
    cb = JudgeTokenCallback()
    for _ in range(3):
        cb.on_llm_end(
            _make_result(
                llm_output={"token_usage": {"prompt_tokens": 10, "completion_tokens": 5}}
            )
        )
    assert cb.prompt_tokens == 30
    assert cb.completion_tokens == 15


def test_no_usage_key_does_not_crash_and_leaves_counters_unchanged() -> None:
    cb = JudgeTokenCallback()
    # llm_output present but no "token_usage" key
    cb.on_llm_end(_make_result(llm_output={"model": "gpt-4"}))
    assert cb.prompt_tokens == 0
    assert cb.completion_tokens == 0


def test_none_llm_output_does_not_crash() -> None:
    cb = JudgeTokenCallback()
    cb.on_llm_end(_make_result(llm_output=None))
    assert cb.prompt_tokens == 0
    assert cb.completion_tokens == 0


def test_ollama_generation_info_fallback() -> None:
    """When llm_output has no token_usage, read from generation_info (Ollama)."""
    cb = JudgeTokenCallback()
    result = _make_result(
        llm_output={},
        generations=[[_gen(prompt_eval_count=40, eval_count=8)]],
    )
    cb.on_llm_end(result)
    assert cb.prompt_tokens == 40
    assert cb.completion_tokens == 8


def test_ollama_generation_info_accumulates_multiple_generations() -> None:
    cb = JudgeTokenCallback()
    result = _make_result(
        llm_output={},
        generations=[
            [_gen(prompt_eval_count=20, eval_count=4)],
            [_gen(prompt_eval_count=30, eval_count=6)],
        ],
    )
    cb.on_llm_end(result)
    assert cb.prompt_tokens == 50
    assert cb.completion_tokens == 10


def test_ollama_fallback_only_when_openai_usage_missing() -> None:
    """If llm_output has token_usage, generation_info is NOT read."""
    cb = JudgeTokenCallback()
    result = _make_result(
        llm_output={"token_usage": {"prompt_tokens": 100, "completion_tokens": 20}},
        generations=[[_gen(prompt_eval_count=999, eval_count=999)]],
    )
    cb.on_llm_end(result)
    assert cb.prompt_tokens == 100
    assert cb.completion_tokens == 20


def test_missing_generation_info_does_not_crash() -> None:
    gen_without_info = SimpleNamespace()  # no generation_info attribute at all
    cb = JudgeTokenCallback()
    result = _make_result(
        llm_output=None,
        generations=[[gen_without_info]],
    )
    cb.on_llm_end(result)
    assert cb.prompt_tokens == 0
    assert cb.completion_tokens == 0


def test_partial_token_usage_fields() -> None:
    """If only prompt_tokens is present (completion missing), add only what's there."""
    cb = JudgeTokenCallback()
    cb.on_llm_end(
        _make_result(llm_output={"token_usage": {"prompt_tokens": 25}})
    )
    assert cb.prompt_tokens == 25
    assert cb.completion_tokens == 0


def test_reset_clears_counters() -> None:
    cb = JudgeTokenCallback()
    cb.on_llm_end(
        _make_result(llm_output={"token_usage": {"prompt_tokens": 50, "completion_tokens": 10}})
    )
    cb.reset()
    assert cb.prompt_tokens == 0
    assert cb.completion_tokens == 0
