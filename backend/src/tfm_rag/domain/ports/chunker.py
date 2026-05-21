from dataclasses import dataclass
from typing import Any, Protocol

from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig


@dataclass(frozen=True, slots=True)
class Chunk:
    """One unit of text that will become one Qdrant point.

    `metadata` is forwarded verbatim into the Qdrant point payload alongside
    `tenant_id`, `kb_id`, `source_id`, `chunk_index`, `content`.
    """

    index: int
    text: str
    metadata: dict[str, Any]


class Chunker(Protocol):
    def chunk(self, text: str, config: ChunkingConfig) -> list[Chunk]: ...
