from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

SessionOrigin = Literal["playground", "widget"]


@dataclass(frozen=True, slots=True)
class ChatSession:
    id: UUID
    chatbot_id: UUID
    tenant_id: UUID
    origin: SessionOrigin
    public_session_cookie: str | None
    created_at: datetime
    last_activity_at: datetime
