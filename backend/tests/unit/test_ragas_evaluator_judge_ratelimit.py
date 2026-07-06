"""The RAGAS judge (openai/openai_compat) gets:
- PROACTIVE spacing: a LangChain InMemoryRateLimiter when the credential sets
  min_request_interval_seconds (requests_per_second = 1/interval).
- REACTIVE resilience: a generous max_retries so the openai SDK absorbs 429s
  (honoring Retry-After) even without spacing.
"""
from tfm_rag.infrastructure.evaluation.ragas_evaluator import RagasEvaluator


def _inner(evaluator: RagasEvaluator):
    wrapper = evaluator._build_judge_llm()
    return wrapper.langchain_llm


def test_judge_has_rate_limiter_from_interval() -> None:
    ev = RagasEvaluator(
        base_url="http://localhost:11434", judge_model="qwen",
        embedding_model="bge-m3", judge_provider="openai_compat",
        judge_base_url="https://api.example.com/v1", judge_api_key="sk",
        min_request_interval_seconds=2.0,
    )
    inner = _inner(ev)
    assert inner.rate_limiter is not None
    assert inner.rate_limiter.requests_per_second == 0.5  # 1 / 2.0s
    assert inner.max_retries == 8  # reactive default


def test_judge_no_rate_limiter_when_interval_unset_but_retries_present() -> None:
    ev = RagasEvaluator(
        base_url="http://localhost:11434", judge_model="qwen",
        embedding_model="bge-m3", judge_provider="openai_compat",
        judge_base_url="https://api.example.com/v1", judge_api_key="sk",
    )
    inner = _inner(ev)
    assert inner.rate_limiter is None
    assert inner.max_retries == 8


def test_ollama_judge_ignores_interval() -> None:
    # OllamaLLM doesn't support rate_limiter; interval is a no-op (local, no limit).
    ev = RagasEvaluator(
        base_url="http://localhost:11434", judge_model="llama3.1",
        embedding_model="bge-m3", judge_provider="ollama",
        min_request_interval_seconds=2.0,
    )
    wrapper = ev._build_judge_llm()  # must not raise
    assert wrapper.langchain_llm is not None


def _openai_evaluator(**kw: object) -> RagasEvaluator:
    return RagasEvaluator(
        base_url="http://localhost:11434", judge_model="qwen",
        embedding_model="bge-m3", judge_provider="openai_compat",
        judge_base_url="https://api.example.com/v1", judge_api_key="sk",
        **kw,  # type: ignore[arg-type]
    )


# NOTE: assert on the *raw* judge LLM. RAGAS' LangchainLLMWrapper (used by
# _build_judge_llm) overwrites request_timeout with its own RunConfig default
# (180s); the per-call timeout we set only lives on the raw ChatOpenAI, which is
# what _judge_abstained invokes directly.
def test_judge_default_timeout_is_60(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # No explicit field, no env override → the judge call gets a 60s timeout so
    # it can never block indefinitely (the SSL-hang bug this guards against).
    monkeypatch.delenv("RAGAS_JUDGE_TIMEOUT", raising=False)
    raw = _openai_evaluator()._build_raw_judge_llm()
    assert raw.request_timeout == 60.0


def test_judge_timeout_env_override(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("RAGAS_JUDGE_TIMEOUT", "30")
    raw = _openai_evaluator()._build_raw_judge_llm()
    assert raw.request_timeout == 30.0


def test_judge_timeout_explicit_field_wins(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # The explicit field beats the env default.
    monkeypatch.setenv("RAGAS_JUDGE_TIMEOUT", "30")
    raw = _openai_evaluator(judge_timeout_seconds=12.5)._build_raw_judge_llm()
    assert raw.request_timeout == 12.5
