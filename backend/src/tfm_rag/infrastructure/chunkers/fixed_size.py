from tfm_rag.domain.ports.chunker import Chunk
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig


class FixedSizeChunker:
    """Naive fixed-width chunker — slides a window of `chunk_size` characters
    with a stride of `chunk_size - chunk_overlap`.

    `ChunkingConfig.strategy` is ignored: plan #8 ships one implementation.
    A later plan can introduce per-strategy chunkers behind the same port.
    """

    def chunk(self, text: str, config: ChunkingConfig) -> list[Chunk]:
        text = text.strip()
        if not text:
            return []
        size = config.chunk_size
        stride = size - config.chunk_overlap
        chunks: list[Chunk] = []
        index = 0
        n = len(text)
        i = 0
        while i < n:
            end = min(i + size, n)
            chunks.append(
                Chunk(
                    index=index,
                    text=text[i:end],
                    metadata={"chunk_start": i, "chunk_end": end},
                )
            )
            index += 1
            if end == n:
                break
            i += stride
        return chunks
