from typing import Any, Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class VectorStorePort(Protocol):
    """Stores and searches chunk embeddings, one collection per (tenant, dim).

    Implementations own a single physical vector database. Callers derive
    the collection name themselves (see `collection_name_for` in the
    Qdrant adapter) and pass it explicitly to every method — the port
    itself has no opinion on naming.

    Points are represented as `(point_id, vector, payload)` tuples on
    write and `(point_id, score, payload)` tuples on read, so the port
    signature carries only builtins + `UUID` — no vector-database-specific
    types leak into `application/`.
    """

    async def ensure_collection(self, tenant_id: UUID, dim: int) -> str:
        """Create the collection for (tenant_id, dim) if it doesn't exist.

        Returns the collection name, idempotently.
        """
        ...

    async def upsert_points(
        self,
        *,
        collection: str,
        points: list[tuple[str, list[float], dict[str, Any]]],
    ) -> None:
        """Upsert a list of (point_id, vector, payload) tuples."""
        ...

    async def delete_by_source(
        self,
        *,
        collection: str,
        tenant_id: UUID,
        source_id: UUID,
    ) -> None:
        """Delete all points whose payload matches both tenant_id and source_id."""
        ...

    async def search(
        self,
        *,
        collection: str,
        tenant_id: UUID,
        kb_ids: list[UUID],
        query_vector: list[float],
        top_k: int,
        score_threshold: float | None = None,
    ) -> list[tuple[str, float, dict[str, Any]]]:
        """Run vector search filtered by tenant_id + kb_ids.

        Returns a list of `(point_id, score, payload)` tuples sorted by
        score descending. `score_threshold` is applied as a server-side
        filter when supported.
        """
        ...

    async def health(self) -> bool:
        """Return True iff the underlying vector database is reachable."""
        ...

    async def close(self) -> None:
        """Release any underlying connection/resources."""
        ...
