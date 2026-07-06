from dataclasses import dataclass
from typing import Any
from uuid import UUID

from tfm_rag.domain.value_objects.model_ref import ModelRef


@dataclass(frozen=True, slots=True)
class LLMSelection(ModelRef):
    """Pointer to a (credential, model) tuple used to generate text.

    Alias of ModelRef — kept as a named class so existing import paths and
    isinstance checks continue to work unchanged.  Provider is resolved at
    chat-runtime via endpoint_resolver (Task 2); no catalog validation here.
    """

    # No additional fields — inherits credential_id + model_id from ModelRef.
    # __post_init__, to_dict, and from_dict are all inherited.

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LLMSelection":
        # Intentionally ignores any extra keys (e.g. legacy `provider_id`).
        return cls(
            credential_id=UUID(str(data["credential_id"])),
            model_id=data["model_id"],
        )
