from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.chat.get_session import (
    MessageView,
    SessionDetailView,
    SessionView,
    get_session,
)
from tfm_rag.domain.errors.chat import SessionNotFoundError
from tfm_rag.infrastructure.api.dependencies import (
    get_current_context,
)
from tfm_rag.infrastructure.api.dependencies import (
    get_session as get_db_session,
)
from tfm_rag.infrastructure.persistence.repositories.chat_sessions_repo import (
    ChatMessageRepository,
    ChatSessionRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

router = APIRouter(prefix="/api/sessions", tags=["chat-sessions"])


class _SessionOut(BaseModel):
    id: str
    chatbot_id: str
    origin: str
    created_at: str
    last_activity_at: str

    @classmethod
    def from_view(cls, v: SessionView) -> "_SessionOut":
        return cls(
            id=str(v.id),
            chatbot_id=str(v.chatbot_id),
            origin=v.origin,
            created_at=v.created_at.isoformat(),
            last_activity_at=v.last_activity_at.isoformat(),
        )


class _MessageOut(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    citations: list[dict[str, Any]]
    metadata: dict[str, Any]
    created_at: str

    @classmethod
    def from_view(cls, v: MessageView) -> "_MessageOut":
        return cls(
            id=str(v.id),
            session_id=str(v.session_id),
            role=v.role,
            content=v.content,
            citations=v.citations,
            metadata=v.metadata,
            created_at=v.created_at.isoformat(),
        )


class SessionDetailOut(BaseModel):
    session: _SessionOut
    messages: list[_MessageOut]

    @classmethod
    def from_view(cls, v: SessionDetailView) -> "SessionDetailOut":
        return cls(
            session=_SessionOut.from_view(v.session),
            messages=[_MessageOut.from_view(m) for m in v.messages],
        )


@router.get("/{session_id}", response_model=SessionDetailOut)
async def get_(
    session_id: UUID,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> SessionDetailOut:
    try:
        view = await get_session(
            session_repo=ChatSessionRepository(session, ctx),
            message_repo=ChatMessageRepository(session),
            session_id=session_id,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SessionDetailOut.from_view(view)
