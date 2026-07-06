from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.infrastructure.chunkers.by_paragraph import ByParagraphChunker


def _cfg(size: int = 1000) -> ChunkingConfig:
    return ChunkingConfig(strategy="by_paragraph", chunk_size=size, chunk_overlap=0)


def test_small_paragraphs_pack_into_one_chunk() -> None:
    text = "Para one.\n\nPara two.\n\nPara three."
    chunks = ByParagraphChunker().chunk(text, _cfg(size=1000))
    assert len(chunks) == 1
    assert chunks[0].metadata == {"strategy": "by_paragraph"}


def test_each_large_paragraph_is_its_own_chunk() -> None:
    p1, p2, p3 = "a" * 100, "b" * 100, "c" * 100
    chunks = ByParagraphChunker().chunk(f"{p1}\n\n{p2}\n\n{p3}", _cfg(size=120))
    assert len(chunks) == 3
    assert [c.index for c in chunks] == [0, 1, 2]
    assert chunks[0].text == p1 and chunks[1].text == p2 and chunks[2].text == p3


def test_oversize_paragraph_is_hard_split() -> None:
    chunks = ByParagraphChunker().chunk("z" * 500, _cfg(size=200))
    assert len(chunks) == 3
    assert [len(c.text) for c in chunks] == [200, 200, 100]


def test_empty_and_whitespace_yield_no_chunks() -> None:
    assert ByParagraphChunker().chunk("", _cfg()) == []
    assert ByParagraphChunker().chunk("  \n\n  ", _cfg()) == []


def test_indices_sequential() -> None:
    text = "\n\n".join(["p" * 80 for _ in range(5)])
    chunks = ByParagraphChunker().chunk(text, _cfg(size=100))
    assert [c.index for c in chunks] == list(range(len(chunks)))
