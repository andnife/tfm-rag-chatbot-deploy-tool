from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    email: str
    password_hash: str | None
    google_sub: str | None
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime
    is_superadmin: bool = False
