from uuid import uuid4

import pytest

from tfm_rag.domain.value_objects.citation import Citation
from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk


def _chunk(content: str = "x") -> RetrievedChunk:
    return RetrievedChunk(
        point_id="pid-1",
        content=content,
        source_id=uuid4(),
        source_filename="manual.pdf",
        chunk_index=2,
        score=0.87,
        metadata={"chunk_start": 100, "chunk_end": 200},
    )


def test_citation_from_chunk_promotes_fields() -> None:
    chunk = _chunk("alpha")
    cit = Citation.from_chunk(chunk)
    assert cit.chunk_id == "pid-1"
    assert cit.source_id == chunk.source_id
    assert cit.source_name == "manual.pdf"
    assert cit.score == 0.87
    assert cit.location == "chunk#2"


def test_citation_round_trip_dict() -> None:
    cit = Citation.from_chunk(_chunk())
    data = cit.to_dict()
    assert set(data) == {
        "chunk_id", "source_id", "source_name", "location", "score", "preview"
    }
    assert data["source_id"] == str(cit.source_id)
    assert data["score"] == cit.score
    cit2 = Citation.from_dict(data)
    assert cit2 == cit


def test_citation_rejects_score_out_of_range() -> None:
    from tfm_rag.domain.errors.common import ValidationError
    with pytest.raises(ValidationError):
        Citation(
            chunk_id="x", source_id=uuid4(), source_name="x",
            location="x", score=1.5,
        )
