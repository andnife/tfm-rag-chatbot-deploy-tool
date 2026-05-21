from dataclasses import dataclass
from typing import Any
from uuid import UUID

from tfm_rag.domain.catalog.llm_providers import LLM_PROVIDER_CATALOG
from tfm_rag.domain.errors.common import ValidationError


@dataclass(frozen=True, slots=True)
class LLMSelection:
    """Pointer to a (provider, credential, model) tuple used to generate text.

    Symmetric to `EmbeddingSelection` from plan #7. Validates against
    `LLM_PROVIDER_CATALOG` only — deeper checks (does the model exist on the
    server, does the credential authenticate) happen at chat-runtime in
    plan #15.
    """

    provider_id: str
    credential_id: UUID
    model_id: str

    def __post_init__(self) -> None:
        descriptor = LLM_PROVIDER_CATALOG.get(self.provider_id)
        if descriptor is None:
            raise ValidationError(
                f"Unknown LLM provider: {self.provider_id!r}"
            )
        # Models inside the catalog are advisory (`default_models`). If the
        # tuple is empty (e.g. openai_compat) we accept any model_id.
        known = set(descriptor.default_models)
        if known and self.model_id not in known:
            raise ValidationError(
                f"Model {self.model_id!r} is not in the catalog for "
                f"provider {self.provider_id!r}. Known: {sorted(known)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "credential_id": str(self.credential_id),
            "model_id": self.model_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LLMSelection":
        return cls(
            provider_id=data["provider_id"],
            credential_id=UUID(str(data["credential_id"])),
            model_id=data["model_id"],
        )
