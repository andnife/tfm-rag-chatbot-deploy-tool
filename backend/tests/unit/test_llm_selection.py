from uuid import uuid4

import pytest

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.llm_selection import LLMSelection


def test_known_combo_accepted() -> None:
    s = LLMSelection(provider_id="ollama", credential_id=uuid4(), model_id="llama3.1")
    assert s.model_id == "llama3.1"


def test_unknown_provider_rejected() -> None:
    with pytest.raises(ValidationError, match="Unknown LLM provider"):
        LLMSelection(provider_id="not_a_provider", credential_id=uuid4(), model_id="x")


def test_unknown_model_rejected_when_catalog_lists_some() -> None:
    # ollama has a non-empty default_models tuple
    with pytest.raises(ValidationError, match="not in the catalog"):
        LLMSelection(provider_id="ollama", credential_id=uuid4(), model_id="phantom-model")


def test_openai_compat_accepts_any_model() -> None:
    # default_models=() for openai_compat → no model restriction
    s = LLMSelection(
        provider_id="openai_compat",
        credential_id=uuid4(),
        model_id="some-custom/model-7b",
    )
    assert s.model_id == "some-custom/model-7b"


def test_round_trip() -> None:
    cid = uuid4()
    s = LLMSelection(provider_id="ollama", credential_id=cid, model_id="llama3.1")
    assert LLMSelection.from_dict(s.to_dict()) == s
