from dataclasses import dataclass
from typing import Any
from uuid import UUID

from tfm_rag.domain.errors.common import ValidationError


@dataclass(frozen=True, slots=True)
class ModelRef:
    """Pointer to a (credential, model) pair — provider resolved at runtime.

    `credential_id` is the ProviderCredential row id.  The provider is
    NOT stored here; it is resolved at call-time via the credential row
    (endpoint_resolver).  No catalog validation of provider — that would
    couple the domain to a specific catalog snapshot.
    """

    credential_id: UUID
    model_id: str

    def __post_init__(self) -> None:
        if not self.model_id or not self.model_id.strip():
            raise ValidationError("model_id must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        return {
            "credential_id": str(self.credential_id),
            "model_id": self.model_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelRef":
        # Intentionally ignores any extra keys (e.g. legacy `provider_id`).
        return cls(
            credential_id=UUID(str(data["credential_id"])),
            model_id=data["model_id"],
        )


@dataclass(frozen=True, slots=True)
class EmbeddingRef(ModelRef):
    """Extends ModelRef with the embedding dimension.

    `dim` defines the Qdrant collection vector size; a wrong dim surfaces
    as a dimension-mismatch error at ingest-runtime, not here.
    """

    dim: int

    def __post_init__(self) -> None:
        # Inline parent validation — super() doesn't work reliably with
        # frozen+slots dataclass inheritance in Python 3.10+.
        if not self.model_id or not self.model_id.strip():
            raise ValidationError("model_id must be a non-empty string")
        if self.dim <= 0:
            raise ValidationError(
                f"dim must be a positive integer, got {self.dim}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "credential_id": str(self.credential_id),
            "model_id": self.model_id,
            "dim": self.dim,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EmbeddingRef":
        # Intentionally ignores any extra keys (e.g. legacy `provider_id`).
        return cls(
            credential_id=UUID(str(data["credential_id"])),
            model_id=data["model_id"],
            dim=int(data["dim"]),
        )
