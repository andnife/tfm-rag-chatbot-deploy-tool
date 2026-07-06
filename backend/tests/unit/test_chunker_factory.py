from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.infrastructure.chunkers.by_paragraph import ByParagraphChunker
from tfm_rag.infrastructure.chunkers.factory import select_chunker
from tfm_rag.infrastructure.chunkers.fixed_size import FixedSizeChunker
from tfm_rag.infrastructure.chunkers.recursive import RecursiveChunker


def _cfg(strategy: str) -> ChunkingConfig:
    return ChunkingConfig(strategy=strategy, chunk_size=1000, chunk_overlap=200)


def test_recursive_strategy_returns_recursive_chunker() -> None:
    assert isinstance(select_chunker(_cfg("recursive")), RecursiveChunker)


def test_by_paragraph_strategy_returns_by_paragraph_chunker() -> None:
    assert isinstance(select_chunker(_cfg("by_paragraph")), ByParagraphChunker)


def test_fixed_strategy_returns_fixed_chunker() -> None:
    assert isinstance(select_chunker(_cfg("fixed")), FixedSizeChunker)
