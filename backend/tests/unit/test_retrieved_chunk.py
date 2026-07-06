from uuid import uuid4

from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk


def test_retrieved_chunk_is_hashable_via_frozen_dataclass() -> None:
    src = uuid4()
    c = RetrievedChunk(
        point_id="p1",
        content="hello",
        source_id=src,
        source_filename="x.txt",
        chunk_index=0,
        score=0.92,
        metadata={"chunk_start": 0},
    )
    # frozen=True → can be put in a set
    assert {c, c} == {c}
    assert c.score == 0.92


def test_retrieved_chunk_default_metadata_is_empty() -> None:
    c = RetrievedChunk(
        point_id="p1",
        content="hello",
        source_id=uuid4(),
        source_filename="x.txt",
        chunk_index=0,
        score=1.0,
    )
    assert c.metadata == {}
