from uuid import uuid4

import pytest

from tfm_rag.infrastructure.settings import Settings
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore


@pytest.mark.integration
async def test_qdrant_ensure_collection_idempotent(settings: Settings) -> None:
    store = QdrantStore(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    tenant = uuid4()
    try:
        n1 = await store.ensure_collection(tenant, dim=1024)
        n2 = await store.ensure_collection(tenant, dim=1024)
        assert n1 == n2
        assert await store.health() is True
    finally:
        # Cleanup
        await store._client.delete_collection(n1)
        await store.close()
