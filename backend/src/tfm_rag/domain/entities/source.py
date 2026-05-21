from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

SourceType = Literal["document", "database"]
IngestStatus = Literal["not_started", "queued", "running", "done", "failed"]


@dataclass(frozen=True, slots=True)
class Source:
    """Polymorphic source row. `type` selects the schema of `payload`.

    payload (document):
        kind: 'upload' | 'cloud'
        storage_uri | cloud_folder_ref
        filename, mime_type, size_bytes, cloud_provider?
    payload (database):
        driver: 'postgres' | 'mysql'
        credential_id, host, port, db_name, ssl_mode, schema_snapshot?
    """

    id: UUID
    kb_id: UUID
    type: SourceType
    payload: dict[str, Any]
    ingest_status: IngestStatus
    last_ingest_at: datetime | None
    error: str | None
