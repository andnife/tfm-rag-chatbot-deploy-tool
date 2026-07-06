from dataclasses import dataclass
from typing import Any
from uuid import UUID

from tfm_rag.domain.value_objects.model_ref import EmbeddingRef


@dataclass(frozen=True, slots=True)
class EmbeddingSelection(EmbeddingRef):
    """Frozen pointer to a (credential, model, dim) tuple.

    Alias of EmbeddingRef — kept as a named class so existing import paths
    and isinstance checks continue to work unchanged.  Provider is resolved
    at ingest-runtime via endpoint_resolver; no catalog validation here.
    """

    # No additional fields — inherits credential_id + model_id + dim from EmbeddingRef.
    # __post_init__, to_dict, and from_dict are all inherited.

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EmbeddingSelection":
        # Intentionally ignores any extra keys (e.g. legacy `provider_id`).
        return cls(
            credential_id=UUID(str(data["credential_id"])),
            model_id=data["model_id"],
            dim=int(data["dim"]),
        )
