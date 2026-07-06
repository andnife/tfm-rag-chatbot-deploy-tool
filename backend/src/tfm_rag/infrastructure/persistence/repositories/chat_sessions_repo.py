from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.entities.chat_message import ChatMessage, MessageRole
from tfm_rag.domain.entities.chat_session import ChatSession, SessionOrigin
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

    @staticmethod
    def _to_entity(row: ChatSessionRow) -> ChatSession:
        return ChatSession(
            id=row.id,
            chatbot_id=row.chatbot_id,
            tenant_id=row.tenant_id,
            origin=cast(SessionOrigin, row.origin),
            public_session_cookie=row.public_session_cookie,
            created_at=row.created_at,
            last_activity_at=row.last_activity_at,
        )

    async def get_chat_session(self, session_id: UUID) -> ChatSession:
        """Domain-typed read. Raises NotFoundError if missing in the tenant."""
        return self._to_entity(await self.get(session_id))

    async def create_chat_session(
        self,
        *,
        chatbot_id: UUID,
        origin: SessionOrigin,
        public_session_cookie: str | None,
    ) -> UUID:
        """Persist a new session, stamping tenant_id from the request context.

        Returns the new session id.
        """
        session_id = uuid4()
        row = ChatSessionRow(
            id=session_id,
            chatbot_id=chatbot_id,
            tenant_id=self._ctx.tenant_id,
            origin=origin,
            public_session_cookie=public_session_cookie,
        )
        self._session.add(row)
        await self._session.flush()
        return session_id

    async def list_chat_sessions_by_chatbot(
        self, *, chatbot_id: UUID, limit: int, offset: int
    ) -> list[ChatSession]:
        """Domain-typed listing, most-recently-active first."""
        rows = await self.list_by_chatbot(
            chatbot_id=chatbot_id, limit=limit, offset=offset
        )
        return [self._to_entity(r) for r in rows]

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

    @staticmethod
    def _to_entity(row: ChatMessageRow) -> ChatMessage:
        return ChatMessage(
            id=row.id,
            session_id=row.session_id,
            role=cast(MessageRole, row.role),
            content=row.content,
            citations=row.citations,
            metadata=row.metadata_,
            created_at=row.created_at,
        )

    async def list_messages_by_session(
        self, session_id: UUID
    ) -> list[ChatMessage]:
        """Domain-typed listing in chronological order."""
        return [
            self._to_entity(r) for r in await self.list_by_session(session_id)
        ]

    async def append_message(
        self,
        *,
        session_id: UUID,
        role: MessageRole,
        content: str,
        citations: list[dict[str, Any]] | None,
        metadata: dict[str, Any] | None,
    ) -> ChatMessage:
        """Append a message turn and return the persisted entity."""
        row = await self.append(
            session_id=session_id,
            role=role,
            content=content,
            citations=citations,
            metadata=metadata,
        )
        return self._to_entity(row)

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
