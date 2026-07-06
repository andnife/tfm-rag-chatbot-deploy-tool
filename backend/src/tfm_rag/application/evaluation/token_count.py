"""Deterministic token counting for the pre-index cost estimate.

Uses tiktoken cl100k_base — exact for OpenAI-family models, an approximation
for other providers (Gemini/Ollama). The runtime cost uses real provider
usage; this module is only for the pre-index estimate where no call exists yet.
"""
import tiktoken

from tfm_rag.domain.ports.chunker import Chunker
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig

_ENC = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_ENC.encode(text))


def estimate_indexing_tokens(
    text: str,
    chunking_config: ChunkingConfig,
    *,
    chunker: Chunker,
) -> dict[str, int]:
    chunks = chunker.chunk(text, chunking_config)
    total = sum(count_tokens(c.text) for c in chunks)
    return {"num_chunks": len(chunks), "total_tokens": total}
