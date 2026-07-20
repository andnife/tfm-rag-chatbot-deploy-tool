from uuid import UUID

from tfm_rag.domain.ports.vector_store import VectorStorePort
from tfm_rag.infrastructure.vector_store.qdrant_client import (
    QdrantStore,
    collection_name_for,
)


def test_collection_name_derivation() -> None:
    tenant = UUID("a1b2c3d4-e5f6-7890-1234-567890abcdef")
    assert collection_name_for(tenant, dim=1024) == \
        "kb_chunks__a1b2c3d4-e5f6-7890-1234-567890abcdef__1024"


def test_collection_name_rejects_invalid_dim() -> None:
    import pytest  # noqa: PLC0415
    tenant = UUID("a1b2c3d4-e5f6-7890-1234-567890abcdef")
    with pytest.raises(ValueError, match="dim must be positive"):
        collection_name_for(tenant, dim=0)


class _FakeAsyncClient:
    """Minimal stand-in for AsyncQdrantClient.query_points."""

    def __init__(self, exc: Exception | None = None) -> None:
        self._exc = exc

    async def query_points(self, **kwargs: object) -> object:
        if self._exc is not None:
            raise self._exc
        raise AssertionError("query_points should not be reached in this test")


async def _search(store: QdrantStore) -> list:
    return await store.search(
        collection="kb_chunks__" + "a" * 8 + "-0000-0000-0000-000000000000__1024",
        tenant_id=UUID("aaaaaaaa-0000-0000-0000-000000000000"),
        kb_ids=[UUID("bbbbbbbb-0000-0000-0000-000000000000")],
        query_vector=[0.1] * 1024,
        top_k=5,
        score_threshold=None,
    )


def test_search_returns_empty_when_collection_missing() -> None:
    """A never-ingested KB has no Qdrant collection. Searching it must degrade
    to no results (→ the pipeline abstains), not raise a raw 500."""
    import asyncio  # noqa: PLC0415

    from qdrant_client.http.exceptions import UnexpectedResponse  # noqa: PLC0415

    store = QdrantStore(url="http://localhost:1", api_key=None)
    store._client = _FakeAsyncClient(  # type: ignore[assignment]
        UnexpectedResponse(status_code=404, reason_phrase="Not Found",
                           content=b"Collection not found", headers=None)
    )
    assert asyncio.run(_search(store)) == []


def test_search_reraises_non_404_errors() -> None:
    """A real Qdrant outage (not a missing collection) must NOT be swallowed."""
    import asyncio  # noqa: PLC0415

    import pytest  # noqa: PLC0415
    from qdrant_client.http.exceptions import UnexpectedResponse  # noqa: PLC0415

    store = QdrantStore(url="http://localhost:1", api_key=None)
    store._client = _FakeAsyncClient(  # type: ignore[assignment]
        UnexpectedResponse(status_code=500, reason_phrase="Internal Server Error",
                           content=b"boom", headers=None)
    )
    with pytest.raises(UnexpectedResponse):
        asyncio.run(_search(store))


def test_qdrant_store_conforms_to_vector_store_port() -> None:
    """QdrantStore satisfies VectorStorePort by structural typing.

    No network I/O happens on construction — AsyncQdrantClient sets up
    lazily — so this is a safe unit-test assertion.
    """
    store = QdrantStore(url="http://localhost:1", api_key=None)
    # NOTE: runtime_checkable isinstance() only verifies attribute *presence*,
    # not method signatures or async-ness. The real signature guard is mypy at
    # every call site that types a value as VectorStorePort.
    assert isinstance(store, VectorStorePort)
