from tfm_rag.application.evaluation.token_count import (
    count_tokens,
    estimate_indexing_tokens,
)
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.infrastructure.chunkers.fixed_size import FixedSizeChunker


def test_count_tokens_nonzero_and_monotonic() -> None:
    assert count_tokens("") == 0
    short = count_tokens("hello")
    longer = count_tokens("hello world this is a longer sentence")
    assert short > 0
    assert longer > short


def test_estimate_indexing_tokens_sums_over_chunks() -> None:
    text = "word " * 500  # ~2500 chars
    cfg = ChunkingConfig.default()
    out = estimate_indexing_tokens(text, cfg, chunker=FixedSizeChunker())
    assert out["num_chunks"] >= 1
    assert out["total_tokens"] > 0
    # total tokens roughly equals counting the whole text (± overlap double-count)
    assert out["total_tokens"] >= count_tokens(text) * 0.5
