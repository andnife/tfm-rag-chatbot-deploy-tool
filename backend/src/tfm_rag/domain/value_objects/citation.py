from dataclasses import dataclass
from typing import Any
from uuid import UUID

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk


@dataclass(frozen=True, slots=True)
class Citation:
    """A reference attached to an assistant message. Pointer back to the
    chunk that grounded a piece of the answer.

    `location` is a human-readable hint about where in the source the chunk
    lives (e.g. `"chunk#7"`, `"page 12"`). For MVP we derive it from
    `chunk_index`; loaders can override later by passing a richer
    `metadata.location` on the source RetrievedChunk.

    Persisted as a JSONB dict inside `chat_messages.citations[]`. The
    canonical shape is the one returned by `to_dict()`.
    """

    chunk_id: str
    source_id: UUID
    source_name: str
    location: str
    score: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.score <= 1.0):
            raise ValidationError(
                f"Citation.score must be in [0, 1], got {self.score}"
            )

    @classmethod
    def from_chunk(cls, chunk: RetrievedChunk) -> "Citation":
        location = str(chunk.metadata.get("location") or f"chunk#{chunk.chunk_index}")
        return cls(
            chunk_id=chunk.point_id,
            source_id=chunk.source_id,
            source_name=chunk.source_filename,
            location=location,
            score=float(chunk.score),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "source_id": str(self.source_id),
            "source_name": self.source_name,
            "location": self.location,
            "score": self.score,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Citation":
        return cls(
            chunk_id=str(data["chunk_id"]),
            source_id=UUID(str(data["source_id"])),
            source_name=str(data["source_name"]),
            location=str(data["location"]),
            score=float(data["score"]),
        )
