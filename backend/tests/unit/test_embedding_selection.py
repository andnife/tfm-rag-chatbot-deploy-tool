import pytest
from uuid import uuid4

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection


def test_known_combo_accepted() -> None:
    s = EmbeddingSelection(
        provider_id="ollama",
        credential_id=uuid4(),
        model_id="bge-m3",
        dim=1024,
    )
    assert s.dim == 1024


def test_unknown_provider_rejected() -> None:
    with pytest.raises(ValidationError, match="Unknown embedding provider"):
        EmbeddingSelection(
            provider_id="not_a_provider",
            credential_id=uuid4(),
            model_id="x",
            dim=1024,
        )


def test_unknown_model_rejected() -> None:
    with pytest.raises(ValidationError, match="not in the catalog"):
        EmbeddingSelection(
            provider_id="ollama",
            credential_id=uuid4(),
            model_id="bge-m3",
            dim=999,
        )


def test_round_trip() -> None:
    cid = uuid4()
    s = EmbeddingSelection(
        provider_id="ollama",
        credential_id=cid,
        model_id="bge-m3",
        dim=1024,
    )
    assert EmbeddingSelection.from_dict(s.to_dict()) == s
