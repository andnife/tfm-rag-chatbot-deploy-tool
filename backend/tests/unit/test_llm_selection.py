from uuid import uuid4

import pytest

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.llm_selection import LLMSelection


def test_valid_selection_accepted() -> None:
    s = LLMSelection(credential_id=uuid4(), model_id="llama3.1")
    assert s.model_id == "llama3.1"


def test_any_model_id_accepted() -> None:
    # No catalog/provider validation — any non-empty model_id is valid.
    s = LLMSelection(credential_id=uuid4(), model_id="gemma3:1b")
    assert s.model_id == "gemma3:1b"


def test_custom_model_id_accepted() -> None:
    s = LLMSelection(credential_id=uuid4(), model_id="some-custom/model-7b")
    assert s.model_id == "some-custom/model-7b"


def test_empty_model_rejected() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        LLMSelection(credential_id=uuid4(), model_id="  ")


def test_round_trip() -> None:
    cid = uuid4()
    s = LLMSelection(credential_id=cid, model_id="llama3.1")
    d = s.to_dict()
    assert "provider_id" not in d
    assert LLMSelection.from_dict(d) == s


def test_from_dict_ignores_legacy_provider_id() -> None:
    cid = uuid4()
    data = {
        "credential_id": str(cid),
        "model_id": "llama3.1",
        "provider_id": "ollama",  # legacy key — must be silently ignored
    }
    s = LLMSelection.from_dict(data)
    assert s.credential_id == cid
    assert s.model_id == "llama3.1"
    assert not hasattr(s, "provider_id")


def test_to_dict_omits_provider_id() -> None:
    s = LLMSelection(credential_id=uuid4(), model_id="llama3.1")
    d = s.to_dict()
    assert set(d.keys()) == {"credential_id", "model_id"}
