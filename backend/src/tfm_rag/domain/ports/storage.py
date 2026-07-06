from typing import Protocol
from uuid import UUID


class Storage(Protocol):
    """Where uploaded document bytes live before ingestion.

    Implementations return an opaque `storage_uri` from `save`; pass it back
    to `load` to retrieve the same bytes. Plan #8 ships a local-filesystem
    adapter; a future plan can swap in S3 without touching use cases.
    """

    async def save(
        self,
        *,
        tenant_id: UUID,
        source_id: UUID,
        filename: str,
        content: bytes,
    ) -> str: ...

    async def load(self, storage_uri: str) -> bytes: ...

    async def delete(self, storage_uri: str) -> None: ...
