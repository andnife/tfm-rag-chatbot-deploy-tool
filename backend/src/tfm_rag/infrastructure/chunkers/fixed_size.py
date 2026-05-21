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
        i = 0
        index = 0
        n = len(text)
        while i < n:
            chunks.append(
                Chunk(
                    index=index,
                    text=text[i : i + size],
                    metadata={"chunk_start": i, "chunk_end": min(i + size, n)},
                )
            )
            index += 1
            i += stride
            if i + size >= n and i + stride < n:
                # Final partial window
                chunks.append(
                    Chunk(
                        index=index,
                        text=text[i:n],
                        metadata={"chunk_start": i, "chunk_end": n},
                    )
                )
                break
        return chunks
