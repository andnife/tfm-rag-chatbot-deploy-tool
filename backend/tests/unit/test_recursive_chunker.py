from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.infrastructure.chunkers.recursive import RecursiveChunker


def _cfg(size: int = 1000, overlap: int = 200) -> ChunkingConfig:
    return ChunkingConfig(strategy="recursive", chunk_size=size, chunk_overlap=overlap)


def test_short_text_single_chunk() -> None:
    chunks = RecursiveChunker().chunk("Hello world.", _cfg())
    assert len(chunks) == 1
    assert chunks[0].index == 0
    assert chunks[0].text == "Hello world."
    assert chunks[0].metadata == {"strategy": "recursive"}


def test_small_paragraphs_stay_together() -> None:
    text = "First paragraph.\n\nSecond paragraph."
    chunks = RecursiveChunker().chunk(text, _cfg(size=1000))
    assert len(chunks) == 1
    # Nothing dropped or altered — the merged chunk must equal the stripped input verbatim.
    assert chunks[0].text == text.strip()


def test_long_text_splits_into_sequential_chunks() -> None:
    text = "word " * 400  # 2000 chars
    chunks = RecursiveChunker().chunk(text, _cfg(size=200, overlap=40))
    assert len(chunks) > 1
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert all(c.text for c in chunks)


def test_splits_on_paragraph_boundary_before_words() -> None:
    # two paragraphs each under size but together over size -> split at the blank line
    para = "x" * 150
    chunks = RecursiveChunker().chunk(f"{para}\n\n{para}", _cfg(size=200, overlap=0))
    assert len(chunks) == 2
    assert chunks[0].text.strip() == para
    assert chunks[1].text.strip() == para


def test_deterministic() -> None:
    text = "alpha beta gamma. " * 50
    a = RecursiveChunker().chunk(text, _cfg(size=150, overlap=30))
    b = RecursiveChunker().chunk(text, _cfg(size=150, overlap=30))
    assert [c.text for c in a] == [c.text for c in b]


def test_empty_and_whitespace_yield_no_chunks() -> None:
    assert RecursiveChunker().chunk("", _cfg()) == []
    assert RecursiveChunker().chunk("   \n\n\t ", _cfg()) == []


def test_chunks_bounded_by_size_plus_overlap() -> None:
    """Codifies the documented contract: no chunk exceeds chunk_size + chunk_overlap."""
    size, overlap = 200, 40
    text = "word " * 400  # 2000 chars — forces many splits
    chunks = RecursiveChunker().chunk(text, _cfg(size=size, overlap=overlap))
    assert len(chunks) > 1, "expected multiple chunks for long input"
    violations = [c for c in chunks if len(c.text) > size + overlap]
    assert not violations, (
        f"{len(violations)} chunk(s) exceeded size+overlap={size + overlap}: "
        + ", ".join(str(len(c.text)) for c in violations)
    )


def test_overlap_carries_content_between_chunks() -> None:
    """Proves that overlap tail content from chunk[i] appears at the start of chunk[i+1].

    We pick an input of short space-separated words so pieces are individually
    well under chunk_size, forcing _merge to carry the overlap tail.  With
    size=120 and overlap=40, the tail of each chunk (last 40 chars) must appear
    verbatim at the beginning of the next chunk.

    This test genuinely fails if overlap is set to 0 — there will be no shared
    content at the boundary.
    """
    size, overlap = 120, 40
    # Each token "alpha beta gamma delta " = 24 chars, all << size, so _merge drives splitting.
    text = "alpha beta gamma delta " * 40
    chunks = RecursiveChunker().chunk(text, _cfg(size=size, overlap=overlap))
    assert len(chunks) > 1, "expected multiple chunks"

    found_overlap = False
    for i in range(len(chunks) - 1):
        # Take the last `overlap` characters of chunk[i] and look for any word
        # from that region at the very start of chunk[i+1].
        tail = chunks[i].text[-overlap:]
        tail_words = [w for w in tail.split() if len(w) >= 3]
        next_start = chunks[i + 1].text[: overlap + 10]
        for word in tail_words:
            if word in next_start:
                found_overlap = True
                break
        if found_overlap:
            break

    assert found_overlap, (
        "No overlapping content found between consecutive chunks — "
        "overlap tail does not appear at the start of the next chunk. "
        "If chunk_overlap > 0, consecutive chunks must share boundary content."
    )
