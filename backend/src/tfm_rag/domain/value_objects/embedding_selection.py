from dataclasses import dataclass
from typing import Any
from uuid import UUID

from tfm_rag.domain.catalog.embedding_providers import EMBEDDING_PROVIDER_CATALOG
from tfm_rag.domain.errors.common import ValidationError


@dataclass(frozen=True, slots=True)
class EmbeddingSelection:
    """Frozen pointer to a (provider, model, dim) tuple + the credential to use.

    `credential_id` is the ProviderCredential row id (plan #6). For SERVER_ENV
    providers (Ollama) this points to the tenant's `default` Ollama credential
    seeded by BootstrapTenant.
    """

    provider_id: str
    credential_id: UUID
    model_id: str
    dim: int

    def __post_init__(self) -> None:
        descriptor = EMBEDDING_PROVIDER_CATALOG.get(self.provider_id)
        if descriptor is None:
            raise ValidationError(
                f"Unknown embedding provider: {self.provider_id!r}"
            )
        known = {(m, d) for m, d in descriptor.default_models}
        if (self.model_id, self.dim) not in known:
            raise ValidationError(
                f"Model ({self.model_id!r}, dim={self.dim}) is not in the "
                f"catalog for provider {self.provider_id!r}. "
                f"Known: {sorted(known)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "credential_id": str(self.credential_id),
            "model_id": self.model_id,
            "dim": self.dim,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EmbeddingSelection":
        return cls(
            provider_id=data["provider_id"],
            credential_id=UUID(str(data["credential_id"])),
            model_id=data["model_id"],
            dim=int(data["dim"]),
        )
