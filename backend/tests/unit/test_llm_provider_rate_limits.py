"""OpenAI gets recommended rate-limit defaults; openai_compat does not.

The judge's effective rate limits resolve with precedence:
explicit credential value → provider recommended default → None (global default).
"""
from tfm_rag.domain.catalog.llm_providers import (
    LLM_PROVIDER_CATALOG,
    resolve_rate_limits,
)


def test_openai_descriptor_carries_recommended_concurrency() -> None:
    openai = LLM_PROVIDER_CATALOG["openai"]
    assert openai.recommended_max_concurrency == 8
    assert openai.recommended_min_request_interval_seconds is None


def test_compat_and_ollama_have_no_recommended_limits() -> None:
    for pid in ("openai_compat", "ollama"):
        d = LLM_PROVIDER_CATALOG[pid]
        assert d.recommended_max_concurrency is None
        assert d.recommended_min_request_interval_seconds is None


def test_explicit_credential_value_wins_over_recommended() -> None:
    # OpenAI with an explicit max_concurrency overrides the recommended 8.
    max_c, min_i = resolve_rate_limits("openai", cred_max_concurrency=20, cred_min_interval=None)
    assert max_c == 20
    assert min_i is None


def test_openai_falls_back_to_recommended_when_unset() -> None:
    max_c, min_i = resolve_rate_limits("openai", cred_max_concurrency=None, cred_min_interval=None)
    assert max_c == 8
    assert min_i is None


def test_compat_falls_back_to_none_when_unset() -> None:
    # openai_compat has no recommended default → None (caller uses its global default).
    max_c, min_i = resolve_rate_limits(
        "openai_compat", cred_max_concurrency=None, cred_min_interval=None
    )
    assert max_c is None
    assert min_i is None


def test_compat_explicit_value_is_honoured() -> None:
    max_c, min_i = resolve_rate_limits(
        "openai_compat", cred_max_concurrency=4, cred_min_interval=2.0
    )
    assert max_c == 4
    assert min_i == 2.0
