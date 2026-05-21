import pytest

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig


def test_default_is_valid() -> None:
    c = ChunkingConfig.default()
    assert c.strategy == "recursive"
    assert c.chunk_size == 1000
    assert c.chunk_overlap == 200


def test_round_trip() -> None:
    c = ChunkingConfig(strategy="fixed", chunk_size=512, chunk_overlap=64)
    assert ChunkingConfig.from_dict(c.to_dict()) == c


def test_chunk_size_below_min_rejected() -> None:
    with pytest.raises(ValidationError):
        ChunkingConfig(strategy="recursive", chunk_size=10, chunk_overlap=0)


def test_chunk_size_above_max_rejected() -> None:
    with pytest.raises(ValidationError):
        ChunkingConfig(strategy="recursive", chunk_size=10_000, chunk_overlap=0)


def test_overlap_greater_than_size_rejected() -> None:
    with pytest.raises(ValidationError):
        ChunkingConfig(strategy="recursive", chunk_size=500, chunk_overlap=600)


def test_overlap_equal_to_size_rejected() -> None:
    with pytest.raises(ValidationError):
        ChunkingConfig(strategy="recursive", chunk_size=500, chunk_overlap=500)
