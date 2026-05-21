from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """One result from vector search. Shape returned by both Qdrant and Reranker.

    `point_id` is the Qdrant point id (a UUIDv5 derived from
    `(source_id, chunk_index)` — see plan #8 `_point_id`).
    `metadata` carries the rest of the payload that's not promoted to fields
    (e.g. `chunk_start`, `chunk_end`, `kb_id`).
    """

    point_id: str
    content: str
    source_id: UUID
    source_filename: str
    chunk_index: int
    score: float
    metadata: dict[str, Any] = field(default_factory=dict, hash=False)
