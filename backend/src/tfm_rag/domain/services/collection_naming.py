"""Pure derivation of the vector-store collection name for a (tenant, dim) pair.

Domain-owned name logic (spec §9 — one physical collection per (tenant, dim)).
Lives in the domain so `application/` can derive the collection name without
importing the Qdrant adapter; the adapter re-exports it for its own use.
"""
from uuid import UUID


def collection_name_for(tenant_id: UUID, dim: int) -> str:
    """Derive the vector-store collection name for a (tenant, dim) pair."""
    if dim <= 0:
        raise ValueError("dim must be positive")
    return f"kb_chunks__{tenant_id}__{dim}"
