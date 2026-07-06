from tfm_rag.domain.ports.chunker import Chunk
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig

_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


class RecursiveChunker:
    """Splits text on natural boundaries (paragraphs -> lines -> sentences ->
    words -> characters), recursing into pieces that still exceed ``chunk_size``,
    then merges adjacent pieces up to ``chunk_size`` carrying a ``chunk_overlap``
    tail between chunks. Routed here when ``config.strategy == "recursive"``.

    **Overlap contract:** to preserve the configured overlap, an emitted chunk
    may be up to ``chunk_size + chunk_overlap`` characters — the overlap tail is
    carried into the next chunk rather than dropped, so the hard ceiling on any
    single chunk is ``chunk_size + chunk_overlap``, not ``chunk_size`` alone."""

    def chunk(self, text: str, config: ChunkingConfig) -> list[Chunk]:
        text = text.strip()
        if not text:
            return []
        pieces = self._split(text, _SEPARATORS, config.chunk_size)
        merged = self._merge(pieces, config.chunk_size, config.chunk_overlap)
        return [
            Chunk(index=i, text=t, metadata={"strategy": "recursive"})
            for i, t in enumerate(merged)
        ]

    def _split(self, text: str, separators: list[str], size: int) -> list[str]:
        if len(text) <= size:
            return [text] if text else []
        sep, rest = separators[0], separators[1:]
        if sep == "":
            return [text[i : i + size] for i in range(0, len(text), size)]
        parts = text.split(sep)
        pieces: list[str] = []
        for idx, part in enumerate(parts):
            piece = part + sep if idx < len(parts) - 1 else part
            if not piece:
                continue
            if len(piece) <= size:
                pieces.append(piece)
            else:
                pieces.extend(self._split(piece, rest, size))
        return pieces

    def _merge(self, pieces: list[str], size: int, overlap: int) -> list[str]:
        chunks: list[str] = []
        current = ""
        for piece in pieces:
            if current and len(current) + len(piece) > size:
                chunks.append(current)
                tail = current[-overlap:] if overlap else ""
                current = tail + piece
            else:
                current += piece
        if current:
            chunks.append(current)
        return [c.strip() for c in chunks if c.strip()]
