from uuid import UUID

from tfm_rag.infrastructure.vector_store.qdrant_client import (
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
