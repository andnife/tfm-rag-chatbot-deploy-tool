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
