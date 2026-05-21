from typing import Any
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)


def collection_name_for(tenant_id: UUID, dim: int) -> str:
    """Derive the Qdrant collection name for a (tenant, dim) pair.

    See spec §9 — one physical collection per (tenant, dim).
    """
    if dim <= 0:
        raise ValueError("dim must be positive")
    return f"kb_chunks__{tenant_id}__{dim}"


class QdrantStore:
    """Thin async wrapper around AsyncQdrantClient with on-demand collections."""

    def __init__(self, url: str, api_key: str | None = None) -> None:
        self._client = AsyncQdrantClient(url=url, api_key=api_key)

    async def ensure_collection(self, tenant_id: UUID, dim: int) -> str:
        name = collection_name_for(tenant_id, dim)
        existing = {c.name for c in (await self._client.get_collections()).collections}
        if name not in existing:
            await self._client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
        return name

    async def upsert_points(
        self,
        *,
        collection: str,
        points: list[tuple[str, list[float], dict[str, Any]]],
    ) -> None:
        """Upsert a list of (point_id, vector, payload) tuples."""
        await self._client.upsert(
            collection_name=collection,
            points=[
                PointStruct(id=pid, vector=vec, payload=payload)
                for pid, vec, payload in points
            ],
        )

    async def delete_by_source(
        self,
        *,
        collection: str,
        tenant_id: UUID,
        source_id: UUID,
    ) -> None:
        """Delete all points whose payload matches both tenant_id and source_id."""
        await self._client.delete(
            collection_name=collection,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="tenant_id",
                            match=MatchValue(value=str(tenant_id)),
                        ),
                        FieldCondition(
                            key="source_id",
                            match=MatchValue(value=str(source_id)),
                        ),
                    ]
                )
            ),
        )

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

        Returns a list of `(point_id, score, payload)` tuples sorted by score
        descending. `score_threshold` is applied as a `score_threshold`
        argument to Qdrant (server-side filter).
        """
        if not kb_ids:
            return []
        kb_ids_str = [str(k) for k in kb_ids]
        result = await self._client.search(
            collection_name=collection,
            query_vector=query_vector,
            limit=top_k,
            score_threshold=score_threshold,
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="tenant_id",
                        match=MatchValue(value=str(tenant_id)),
                    ),
                    FieldCondition(
                        key="kb_id",
                        match=MatchAny(any=kb_ids_str),
                    ),
                ]
            ),
            with_payload=True,
        )
        out: list[tuple[str, float, dict[str, Any]]] = []
        for hit in result:
            out.append((str(hit.id), float(hit.score), dict(hit.payload or {})))
        return out

    async def health(self) -> bool:
        try:
            await self._client.get_collections()
            return True
        except Exception:  # noqa: BLE001
            return False

    async def close(self) -> None:
        await self._client.close()
