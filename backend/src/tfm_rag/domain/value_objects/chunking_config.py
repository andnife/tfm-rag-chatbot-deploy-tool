from dataclasses import dataclass
from typing import Any, Literal

from tfm_rag.domain.errors.common import ValidationError

ChunkingStrategy = Literal["recursive", "by_paragraph", "fixed"]

CHUNK_SIZE_MIN = 100
CHUNK_SIZE_MAX = 4000
CHUNK_OVERLAP_MIN = 0
CHUNK_OVERLAP_MAX = 500


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    strategy: ChunkingStrategy
    chunk_size: int
    chunk_overlap: int

    def __post_init__(self) -> None:
        if not (CHUNK_SIZE_MIN <= self.chunk_size <= CHUNK_SIZE_MAX):
            raise ValidationError(
                f"chunk_size must be in [{CHUNK_SIZE_MIN},{CHUNK_SIZE_MAX}], "
                f"got {self.chunk_size}"
            )
        if not (CHUNK_OVERLAP_MIN <= self.chunk_overlap <= CHUNK_OVERLAP_MAX):
            raise ValidationError(
                f"chunk_overlap must be in [{CHUNK_OVERLAP_MIN},{CHUNK_OVERLAP_MAX}], "
                f"got {self.chunk_overlap}"
            )
        if self.chunk_overlap >= self.chunk_size:
            raise ValidationError(
                f"chunk_overlap ({self.chunk_overlap}) must be < "
                f"chunk_size ({self.chunk_size})"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChunkingConfig":
        return cls(
            strategy=data["strategy"],
            chunk_size=int(data["chunk_size"]),
            chunk_overlap=int(data["chunk_overlap"]),
        )

    @classmethod
    def default(cls) -> "ChunkingConfig":
        return cls(strategy="recursive", chunk_size=1000, chunk_overlap=200)
