from uuid import uuid4

import pytest

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection


def test_valid_selection_accepted() -> None:
    s = EmbeddingSelection(credential_id=uuid4(), model_id="bge-m3", dim=1024)
    assert s.dim == 1024


def test_any_model_id_accepted() -> None:
    # No catalog/provider validation — any non-empty model_id is valid.
    s = EmbeddingSelection(
        credential_id=uuid4(),
        model_id="gemini-embedding-001",
        dim=3072,
    )
    assert s.model_id == "gemini-embedding-001"
    assert s.dim == 3072


def test_empty_model_rejected() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        EmbeddingSelection(credential_id=uuid4(), model_id="  ", dim=1024)


def test_non_positive_dim_rejected() -> None:
    with pytest.raises(ValidationError, match="positive"):
        EmbeddingSelection(credential_id=uuid4(), model_id="bge-m3", dim=0)


def test_round_trip() -> None:
    cid = uuid4()
    s = EmbeddingSelection(credential_id=cid, model_id="bge-m3", dim=1024)
    d = s.to_dict()
    assert "provider_id" not in d
    assert EmbeddingSelection.from_dict(d) == s


def test_from_dict_ignores_legacy_provider_id() -> None:
    cid = uuid4()
    data = {
        "credential_id": str(cid),
        "model_id": "bge-m3",
        "dim": 1024,
        "provider_id": "ollama",  # legacy key — must be silently ignored
    }
    s = EmbeddingSelection.from_dict(data)
    assert s.credential_id == cid
    assert s.model_id == "bge-m3"
    assert s.dim == 1024
    assert not hasattr(s, "provider_id")


def test_to_dict_omits_provider_id() -> None:
    s = EmbeddingSelection(credential_id=uuid4(), model_id="bge-m3", dim=1024)
    d = s.to_dict()
    assert set(d.keys()) == {"credential_id", "model_id", "dim"}
