from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.infrastructure.persistence.models.chat_messages import (
    ChatMessageRow,
)
from tfm_rag.infrastructure.persistence.models.chat_sessions import (
    ChatSessionRow,
)
from tfm_rag.infrastructure.persistence.repository import (
    BaseRepository,
)


class ChatSessionRepository(BaseRepository[ChatSessionRow]):
    """Tenant-scoped sessions via the denormalised tenant_id column."""

    model = ChatSessionRow

    async def list_by_chatbot(
        self, *, chatbot_id: UUID, limit: int = 20, offset: int = 0
    ) -> list[ChatSessionRow]:
        stmt = (
            select(ChatSessionRow)
            .where(
                ChatSessionRow.tenant_id == self._ctx.tenant_id,
                ChatSessionRow.chatbot_id == chatbot_id,
            )
            .order_by(desc(ChatSessionRow.last_activity_at))
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def find_by_public_cookie(
        self, cookie: str
    ) -> ChatSessionRow | None:
        """Lookup used by the public widget endpoint (plan #16). Tenant
        isolation NOT enforced here — the cookie value is the credential.
        """
        stmt = select(ChatSessionRow).where(
            ChatSessionRow.public_session_cookie == cookie
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def touch(self, session_id: UUID) -> None:
        """Bump last_activity_at to NOW for the session. Tenant-checked."""
        await self._session.execute(
            update(ChatSessionRow)
            .where(
                ChatSessionRow.id == session_id,
                ChatSessionRow.tenant_id == self._ctx.tenant_id,
            )
            .values(last_activity_at=datetime.now(UTC))
        )


class ChatMessageRepository:
    """Messages are scoped through their parent session (which is
    tenant-scoped via ChatSessionRepository).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_session(self, session_id: UUID) -> list[ChatMessageRow]:
        stmt = (
            select(ChatMessageRow)
            .where(ChatMessageRow.session_id == session_id)
            .order_by(ChatMessageRow.created_at.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def append(
        self,
        *,
        session_id: UUID,
        role: str,
        content: str,
        citations: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessageRow:
        from uuid import uuid4

        row = ChatMessageRow(
            id=uuid4(),
            session_id=session_id,
            role=role,
            content=content,
            citations=citations or [],
            metadata_=metadata or {},
        )
        self._session.add(row)
        await self._session.flush()
        return row
