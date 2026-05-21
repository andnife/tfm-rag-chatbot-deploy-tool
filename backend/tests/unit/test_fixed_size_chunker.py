from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.infrastructure.chunkers.fixed_size import FixedSizeChunker


def test_chunks_short_text_into_single_chunk() -> None:
    chunker = FixedSizeChunker()
    chunks = chunker.chunk(
        "Hello world.",
        ChunkingConfig(strategy="fixed", chunk_size=1000, chunk_overlap=200),
    )
    assert len(chunks) == 1
    assert chunks[0].text == "Hello world."
    assert chunks[0].index == 0


def test_chunks_long_text_with_overlap() -> None:
    chunker = FixedSizeChunker()
    text = "abcdefghij" * 50  # 500 chars
    chunks = chunker.chunk(
        text,
        ChunkingConfig(strategy="fixed", chunk_size=200, chunk_overlap=50),
    )
    # 500 chars, chunk_size=200, stride=150 → chunks at 0, 150, 300, ... up to len(text)
    assert len(chunks) >= 3
    assert chunks[0].text == text[0:200]
    assert chunks[1].text == text[150:350]
    assert all(c.index == i for i, c in enumerate(chunks))


def test_empty_text_yields_no_chunks() -> None:
    chunker = FixedSizeChunker()
    chunks = chunker.chunk(
        "",
        ChunkingConfig(strategy="fixed", chunk_size=200, chunk_overlap=50),
    )
    assert chunks == []


def test_whitespace_only_text_yields_no_chunks() -> None:
    chunker = FixedSizeChunker()
    chunks = chunker.chunk(
        "   \n\n\t  ",
        ChunkingConfig(strategy="fixed", chunk_size=200, chunk_overlap=50),
    )
    assert chunks == []
