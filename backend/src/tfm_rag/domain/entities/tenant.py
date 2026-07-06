from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Tenant:
    id: UUID
    name: str
    qdrant_collection_prefix: str
    storage_prefix: str
    created_at: datetime
