from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class IngestionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class IngestionJob:
    id: UUID
    source_id: UUID
    tenant_id: UUID
    status: IngestionStatus
    progress: int  # 0..100
    error: str | None
    started_at: datetime
    finished_at: datetime | None
