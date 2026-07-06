from tfm_rag.domain.ports.chunker import Chunker
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig

from .by_paragraph import ByParagraphChunker
from .fixed_size import FixedSizeChunker
from .recursive import RecursiveChunker


def select_chunker(config: ChunkingConfig) -> Chunker:
    """Return the chunker adapter for ``config.strategy``."""
    if config.strategy == "recursive":
        return RecursiveChunker()
    if config.strategy == "by_paragraph":
        return ByParagraphChunker()
    return FixedSizeChunker()
