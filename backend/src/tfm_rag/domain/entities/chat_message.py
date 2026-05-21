from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

MessageRole = Literal["user", "assistant", "system"]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One turn of a chat session.

    `citations` is `list[dict]` (not a typed VO) in plan #14 — the
    `Citation` VO arrives in plan #15. Each entry follows the spec shape:
        {source_id, source_name, location, chunk_id, score}

    `metadata` is `dict` with a known `iterations` key (list of
    RetrievalIteration shapes, also typed in plan #15).
    """

    id: UUID
    session_id: UUID
    role: MessageRole
    content: str
    citations: list[dict[str, Any]] = field(default_factory=list, hash=False)
    metadata: dict[str, Any] = field(default_factory=dict, hash=False)
    created_at: datetime | None = None
