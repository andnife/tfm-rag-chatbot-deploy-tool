from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

IngestionStatus = Literal["queued", "running", "done", "failed"]
IngestionStage = Literal["extracting", "chunking", "embedding", "indexing"]


@dataclass(frozen=True, slots=True)
class IngestionJob:
    id: UUID
    source_id: UUID
    tenant_id: UUID
    status: IngestionStatus
    progress: int  # 0..100
    stage: str | None
    items_done: int | None
    items_total: int | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None
