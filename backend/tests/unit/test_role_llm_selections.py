from uuid import uuid4

import pytest

from tfm_rag.domain.catalog.llm_roles import (
    ROLE_ANSWER_GENERATOR,
    ROLE_EVALUATOR,
    ROLE_SQL_GENERATOR,
)
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.role_llm_selections import RoleLLMSelections


def _sel(model_id: str = "llama3.1") -> LLMSelection:
    return LLMSelection(credential_id=uuid4(), model_id=model_id)


def test_default_is_all_none() -> None:
    r = RoleLLMSelections.default()
    assert r.evaluator is None
    assert r.sql_generator is None
    assert r.answer_generator is None
    assert r.to_dict() == {}


def test_round_trip_partial_omits_none_keys() -> None:
    r = RoleLLMSelections(evaluator=_sel())
    d = r.to_dict()
    assert set(d.keys()) == {"evaluator"}
    assert RoleLLMSelections.from_dict(d) == r


def test_round_trip_full() -> None:
    r = RoleLLMSelections(
        evaluator=_sel("llama3.1"),
        sql_generator=_sel("llama3.1"),
        answer_generator=_sel("llama3.1"),
    )
    assert RoleLLMSelections.from_dict(r.to_dict()) == r


def test_from_dict_none_and_empty() -> None:
    assert RoleLLMSelections.from_dict(None) == RoleLLMSelections.default()
    assert RoleLLMSelections.from_dict({}) == RoleLLMSelections.default()


def test_resolve_returns_configured_role() -> None:
    sel = _sel()
    r = RoleLLMSelections(evaluator=sel)
    default = _sel("mistral")
    assert r.resolve(ROLE_EVALUATOR, default) is sel


def test_resolve_falls_back_to_default_when_unset() -> None:
    default = _sel("mistral")
    r = RoleLLMSelections(evaluator=_sel())
    assert r.resolve(ROLE_SQL_GENERATOR, default) is default
    assert r.resolve(ROLE_ANSWER_GENERATOR, default) is default


def test_resolve_unknown_role_raises() -> None:
    with pytest.raises(ValidationError, match="Unknown LLM role"):
        RoleLLMSelections.default().resolve("nope", _sel())


def test_from_dict_ignores_legacy_provider_id_in_nested_selection() -> None:
    """from_dict tolerates legacy `provider_id` inside nested LLMSelection dicts."""
    cid = uuid4()
    data = {
        "evaluator": {
            "credential_id": str(cid),
            "model_id": "llama3.1",
            "provider_id": "ollama",  # legacy key — must be silently ignored
        }
    }
    r = RoleLLMSelections.from_dict(data)
    assert r.evaluator is not None
    assert r.evaluator.model_id == "llama3.1"
    assert r.evaluator.credential_id == cid
    assert not hasattr(r.evaluator, "provider_id")
