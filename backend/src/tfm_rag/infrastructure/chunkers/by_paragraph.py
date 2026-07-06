import re

from tfm_rag.domain.ports.chunker import Chunk
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig

_PARAGRAPH = re.compile(r"\n\s*\n")


class ByParagraphChunker:
    """One chunk per paragraph, packing consecutive paragraphs up to
    ``chunk_size`` (joined with a blank line); a single paragraph larger than
    ``chunk_size`` is hard-split by ``chunk_size``. No character overlap —
    boundaries are paragraph-aligned. Routed here when strategy == "by_paragraph"."""

    def chunk(self, text: str, config: ChunkingConfig) -> list[Chunk]:
        text = text.strip()
        if not text:
            return []
        size = config.chunk_size
        paragraphs = [p.strip() for p in _PARAGRAPH.split(text) if p.strip()]
        chunks: list[str] = []
        current = ""
        for para in paragraphs:
            if len(para) > size:
                if current:
                    chunks.append(current)
                    current = ""
                for i in range(0, len(para), size):
                    chunks.append(para[i : i + size])
            elif current and len(current) + 2 + len(para) > size:
                chunks.append(current)
                current = para
            else:
                current = f"{current}\n\n{para}" if current else para
        if current:
            chunks.append(current)
        return [
            Chunk(index=i, text=t, metadata={"strategy": "by_paragraph"})
            for i, t in enumerate(chunks)
        ]
