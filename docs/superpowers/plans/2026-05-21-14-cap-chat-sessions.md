# CAP-CHAT-SESSIONS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Ship `chat_sessions` + `chat_messages` persistence so plan #15 (the agent loop) has somewhere to write user/assistant turns. Two read use cases — `ListSessions(chatbot_id, page)` and `GetSession(session_id) → session + messages` — exposed as `GET /api/chatbots/{chatbot_id}/sessions` and `GET /api/sessions/{session_id}`. Plus three internal helpers (`create_session`, `append_message`, `touch_session`) that the agent loop in #15 will call.

**Architecture:**
- Two tables in migration 0007: `chat_sessions` (FK chatbot_id ON DELETE CASCADE, denormalised tenant_id for defense-in-depth, origin enum, optional `public_session_cookie` for widget sessions) + `chat_messages` (FK session_id ON DELETE CASCADE, role enum, content TEXT, citations JSONB, metadata JSONB).
- Plan #14 ships **read endpoints only**. The write helpers exist as Python functions but no HTTP endpoint creates a session today — plan #15 calls them from inside `POST /api/chatbots/{id}/chat`.
- Tenant scoping on sessions uses the denormalised `tenant_id` column (`BaseRepository[ChatSessionRow]`). Messages are scoped transitively via the session their FK points to (use cases load the session first, then list messages).
- `citations` and `metadata` are kept as opaque JSONB dicts/lists in plan #14. The VOs `Citation` and `RetrievalIteration` will land in plan #15 when they're actually constructed by the agent loop.
- `chatbots ON DELETE CASCADE → chat_sessions ON DELETE CASCADE → chat_messages` chain is what makes plan #10's `DeleteChatbot` "cascada sesiones + mensajes" wording become literally true without any code change in #10.

**Tech Stack:** No new deps.

**Depends on:** plan #10 (chatbots table — FK target for chat_sessions).

**Out of scope (deferred):**
- `AnswerQuery` agent loop + `POST /api/chatbots/{id}/chat` SSE stream → plan #15.
- `Citation` and `RetrievalIteration` typed VOs → plan #15.
- Full-text search over messages, export, manual annotation → not in MVP per spec ficha non-goals.
- Public widget session bootstrap with cookie → covered by plan #16 (CAP-WIDGET-RUNTIME). Plan #14 stores `public_session_cookie` but doesn't issue or read cookies.

---

## File structure

```
backend/src/tfm_rag/
├── domain/
│   ├── entities/
│   │   ├── chat_session.py              # NEW
│   │   └── chat_message.py              # NEW
│   └── errors/
│       └── chat.py                      # MODIFY: +SessionNotFoundError
│
├── infrastructure/persistence/
│   ├── models/
│   │   ├── chat_sessions.py             # NEW
│   │   └── chat_messages.py             # NEW
│   └── repositories/
│       └── chat_sessions_repo.py        # NEW (sessions + messages repo combined)
│
└── application/
    └── chat/
        ├── list_sessions.py             # NEW
        ├── get_session.py               # NEW
        ├── create_session.py            # NEW (internal helper for #15)
        ├── append_message.py            # NEW (internal helper for #15)
        └── touch_session.py             # NEW (internal helper for #15)

backend/alembic/env.py                   # MODIFY: register chat_sessions + chat_messages
backend/alembic/versions/
└── 0007_chat_sessions_and_messages.py   # NEW

backend/src/tfm_rag/infrastructure/api/
├── app.py                                # MODIFY: mount sessions router
└── routers/
    └── sessions.py                       # NEW

backend/src/tfm_rag/infrastructure/api/routers/
└── chatbots.py                           # MODIFY: +GET /{chatbot_id}/sessions

backend/tests/unit/
└── test_chat_sessions_use_cases.py       # NEW

backend/tests/integration/
└── test_chat_sessions_flow.py            # NEW
```

---

## Task 1 — Domain: entities + error

**Files:**
- Create: `backend/src/tfm_rag/domain/entities/chat_session.py`
- Create: `backend/src/tfm_rag/domain/entities/chat_message.py`
- Modify: `backend/src/tfm_rag/domain/errors/chat.py` (add `SessionNotFoundError`)

- [ ] **Step 1.1: Create `backend/src/tfm_rag/domain/entities/chat_session.py`**

```python
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
```

- [ ] **Step 1.2: Create `backend/src/tfm_rag/domain/entities/chat_message.py`**

```python
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
```

- [ ] **Step 1.3: Extend `backend/src/tfm_rag/domain/errors/chat.py`**

Append to the existing module (do NOT remove the previously defined errors):

```python


class SessionNotFoundError(NotFoundError):
    """Raised when a ChatSession is not found in the tenant."""
```

Add the import at the top of the file (merge with the existing `from tfm_rag.domain.errors.common import DomainError` line — it should become):

```python
from tfm_rag.domain.errors.common import DomainError, NotFoundError
```

- [ ] **Step 1.4: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/domain/entities/chat_session.py backend/src/tfm_rag/domain/entities/chat_message.py backend/src/tfm_rag/domain/errors/chat.py
git commit -m "feat(domain): ChatSession + ChatMessage entities + SessionNotFoundError"
```

---

## Task 2 — Persistence: ORM + migration 0007 + repository

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/persistence/models/chat_sessions.py`
- Create: `backend/src/tfm_rag/infrastructure/persistence/models/chat_messages.py`
- Create: `backend/alembic/versions/0007_chat_sessions_and_messages.py`
- Modify: `backend/alembic/env.py` (register the two new modules)
- Create: `backend/src/tfm_rag/infrastructure/persistence/repositories/chat_sessions_repo.py`
- Create: `backend/tests/integration/test_chat_sessions_migration.py`

- [ ] **Step 2.1: Write the failing integration test**

Create `backend/tests/integration/test_chat_sessions_migration.py`:

```python
import asyncio
import subprocess

import pytest
from sqlalchemy import inspect

from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings


@pytest.mark.integration
async def test_migration_0007_creates_chat_tables(settings: Settings) -> None:
    result = await asyncio.to_thread(
        subprocess.run,
        ["alembic", "upgrade", "head"],
        cwd=".",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    engine = build_engine(settings.postgres_url)
    build_session_factory(engine)
    async with engine.connect() as conn:
        tables = await conn.run_sync(
            lambda sc: inspect(sc).get_table_names()
        )
        assert "chat_sessions" in tables
        assert "chat_messages" in tables

        s_cols = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("chat_sessions")}
        )
        assert {
            "id", "chatbot_id", "tenant_id", "origin",
            "public_session_cookie", "created_at", "last_activity_at",
        } <= s_cols

        m_cols = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("chat_messages")}
        )
        assert {
            "id", "session_id", "role", "content",
            "citations", "metadata", "created_at",
        } <= m_cols
    await engine.dispose()
```

- [ ] **Step 2.2: Create `backend/src/tfm_rag/infrastructure/persistence/models/chat_sessions.py`**

```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from tfm_rag.infrastructure.persistence.base import Base


class ChatSessionRow(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        CheckConstraint(
            "origin IN ('playground','widget')",
            name="ck_chat_sessions_origin",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    chatbot_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    public_session_cookie: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
```

- [ ] **Step 2.3: Create `backend/src/tfm_rag/infrastructure/persistence/models/chat_messages.py`**

```python
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from tfm_rag.infrastructure.persistence.base import Base


class ChatMessageRow(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user','assistant','system')",
            name="ck_chat_messages_role",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    # SQLAlchemy reserves the attribute name `metadata` on the declarative
    # Base for its own use. We name the Python attribute `metadata_` and
    # map it to the DB column `metadata` via mapped_column("metadata", ...).
    # The repo + use cases consistently use `.metadata_` for reads/writes
    # and translate to/from `"metadata"` in serialised output.
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 2.4: Create `backend/alembic/versions/0007_chat_sessions_and_messages.py`**

```python
"""create chat_sessions and chat_messages tables

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-21 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "chatbot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chatbots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("public_session_cookie", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "origin IN ('playground','widget')",
            name="ck_chat_sessions_origin",
        ),
    )
    op.create_index("ix_chat_sessions_chatbot_id", "chat_sessions", ["chatbot_id"])
    op.create_index("ix_chat_sessions_tenant_id", "chat_sessions", ["tenant_id"])
    op.create_index(
        "ix_chat_sessions_public_session_cookie",
        "chat_sessions",
        ["public_session_cookie"],
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "citations",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('user','assistant','system')",
            name="ck_chat_messages_role",
        ),
    )
    op.create_index(
        "ix_chat_messages_session_id_created_at",
        "chat_messages",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chat_messages_session_id_created_at",
        table_name="chat_messages",
    )
    op.drop_table("chat_messages")
    op.drop_index(
        "ix_chat_sessions_public_session_cookie",
        table_name="chat_sessions",
    )
    op.drop_index(
        "ix_chat_sessions_tenant_id", table_name="chat_sessions"
    )
    op.drop_index(
        "ix_chat_sessions_chatbot_id", table_name="chat_sessions"
    )
    op.drop_table("chat_sessions")
```

- [ ] **Step 2.5: Register the new models in `backend/alembic/env.py`**

The model-imports block should end up like this (merge alphabetically with existing entries):

```python
from tfm_rag.infrastructure.persistence.models import (
    chat_messages,  # noqa: F401
    chat_sessions,  # noqa: F401
    chatbot_knowledge_base,  # noqa: F401
    chatbots,  # noqa: F401
    ingestion_jobs,  # noqa: F401
    knowledge_bases,  # noqa: F401
    provider_credentials,  # noqa: F401
    sources,  # noqa: F401
    tenants,  # noqa: F401
    users,  # noqa: F401
)
```

- [ ] **Step 2.6: Create `backend/src/tfm_rag/infrastructure/persistence/repositories/chat_sessions_repo.py`**

```python
from datetime import datetime, timezone
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
    RequestContext,
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
            .values(last_activity_at=datetime.now(timezone.utc))
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
```

- [ ] **Step 2.7: Reset DB and run the migration test**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
docker exec tfm-rag-postgres-1 psql -U tfm -d tfm_rag \
  -c "DROP TABLE IF EXISTS chat_messages, chat_sessions, chatbot_knowledge_base, chatbots, ingestion_jobs, sources, knowledge_bases, provider_credentials, users, tenants, alembic_version CASCADE;"
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
pytest tests/integration/test_chat_sessions_migration.py -m integration -v
```

Expected: **1 PASSED**.

- [ ] **Step 2.8: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/infrastructure/persistence/models/chat_sessions.py backend/src/tfm_rag/infrastructure/persistence/models/chat_messages.py backend/alembic/versions/0007_chat_sessions_and_messages.py backend/alembic/env.py backend/src/tfm_rag/infrastructure/persistence/repositories/chat_sessions_repo.py backend/tests/integration/test_chat_sessions_migration.py
git commit -m "feat(infra): chat_sessions + chat_messages ORM + migration 0007 + repositories"
```

---

## Task 3 — Application use cases (5: 2 read + 3 internal write helpers) + unit tests

**Files:**
- Create: `backend/src/tfm_rag/application/chat/list_sessions.py`
- Create: `backend/src/tfm_rag/application/chat/get_session.py`
- Create: `backend/src/tfm_rag/application/chat/create_session.py`
- Create: `backend/src/tfm_rag/application/chat/append_message.py`
- Create: `backend/src/tfm_rag/application/chat/touch_session.py`
- Create: `backend/tests/unit/test_chat_sessions_use_cases.py`

- [ ] **Step 3.1: Write the failing unit tests**

Create `backend/tests/unit/test_chat_sessions_use_cases.py`:

```python
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tfm_rag.application.chat.append_message import append_message
from tfm_rag.application.chat.create_session import create_session
from tfm_rag.application.chat.get_session import get_session
from tfm_rag.application.chat.list_sessions import list_sessions
from tfm_rag.application.chat.touch_session import touch_session
from tfm_rag.domain.errors.chat import SessionNotFoundError
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.infrastructure.persistence.repository import RequestContext


def _ctx() -> RequestContext:
    return RequestContext(tenant_id=uuid4(), user_id=uuid4())


def _session_row(session_id=None, chatbot_id=None, tenant_id=None) -> MagicMock:
    row = MagicMock()
    row.id = session_id or uuid4()
    row.chatbot_id = chatbot_id or uuid4()
    row.tenant_id = tenant_id or uuid4()
    row.origin = "playground"
    row.public_session_cookie = None
    row.created_at = datetime.now(timezone.utc)
    row.last_activity_at = datetime.now(timezone.utc)
    return row


def _message_row(session_id) -> MagicMock:
    row = MagicMock()
    row.id = uuid4()
    row.session_id = session_id
    row.role = "user"
    row.content = "hello"
    row.citations = []
    row.metadata_ = {}
    row.created_at = datetime.now(timezone.utc)
    return row


@pytest.mark.asyncio
async def test_list_sessions_validates_chatbot_and_lists() -> None:
    ctx = _ctx()
    chatbot_repo = MagicMock()
    chatbot_row = MagicMock()
    chatbot_row.id = uuid4()
    chatbot_repo.get = AsyncMock(return_value=chatbot_row)

    session_repo = MagicMock()
    session_repo.list_by_chatbot = AsyncMock(
        return_value=[_session_row(chatbot_id=chatbot_row.id, tenant_id=ctx.tenant_id)]
    )

    session = MagicMock()
    views = await list_sessions(
        session, ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        session_repo_factory=lambda s, c: session_repo,
        chatbot_id=chatbot_row.id,
        limit=10, offset=0,
    )

    chatbot_repo.get.assert_awaited_once_with(chatbot_row.id)
    session_repo.list_by_chatbot.assert_awaited_once_with(
        chatbot_id=chatbot_row.id, limit=10, offset=0
    )
    assert len(views) == 1


@pytest.mark.asyncio
async def test_list_sessions_raises_when_chatbot_missing() -> None:
    ctx = _ctx()
    chatbot_repo = MagicMock()
    chatbot_repo.get = AsyncMock(side_effect=NotFoundError("nope"))
    session_repo = MagicMock()
    session = MagicMock()

    with pytest.raises(ChatbotNotFoundError):
        await list_sessions(
            session, ctx,
            chatbot_repo_factory=lambda s, c: chatbot_repo,
            session_repo_factory=lambda s, c: session_repo,
            chatbot_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_get_session_returns_session_with_messages() -> None:
    ctx = _ctx()
    s_row = _session_row(tenant_id=ctx.tenant_id)
    m_a = _message_row(s_row.id)
    m_b = _message_row(s_row.id)
    session_repo = MagicMock()
    session_repo.get = AsyncMock(return_value=s_row)
    message_repo = MagicMock()
    message_repo.list_by_session = AsyncMock(return_value=[m_a, m_b])

    session = MagicMock()
    detail = await get_session(
        session, ctx,
        session_repo_factory=lambda s, c: session_repo,
        message_repo_factory=lambda s: message_repo,
        session_id=s_row.id,
    )

    assert detail.session.id == s_row.id
    assert len(detail.messages) == 2
    message_repo.list_by_session.assert_awaited_once_with(s_row.id)


@pytest.mark.asyncio
async def test_get_session_raises_when_missing() -> None:
    ctx = _ctx()
    session_repo = MagicMock()
    session_repo.get = AsyncMock(side_effect=NotFoundError("nope"))
    message_repo = MagicMock()
    session = MagicMock()

    with pytest.raises(SessionNotFoundError):
        await get_session(
            session, ctx,
            session_repo_factory=lambda s, c: session_repo,
            message_repo_factory=lambda s: message_repo,
            session_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_create_session_validates_chatbot_and_persists() -> None:
    ctx = _ctx()
    chatbot_row = MagicMock()
    chatbot_row.id = uuid4()
    chatbot_repo = MagicMock()
    chatbot_repo.get = AsyncMock(return_value=chatbot_row)

    captured: dict[str, MagicMock] = {}

    def _add(row: MagicMock) -> None:
        captured["row"] = row

    session = MagicMock()
    session.add = MagicMock(side_effect=_add)
    session.flush = AsyncMock()

    session_id = await create_session(
        session, ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        chatbot_id=chatbot_row.id,
        origin="playground",
        public_session_cookie=None,
    )

    assert session_id == captured["row"].id
    assert captured["row"].chatbot_id == chatbot_row.id
    assert captured["row"].tenant_id == ctx.tenant_id
    assert captured["row"].origin == "playground"
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_session_rejects_widget_without_cookie() -> None:
    """origin=widget requires a public_session_cookie (plan #16 sets it)."""
    from tfm_rag.domain.errors.common import ValidationError

    ctx = _ctx()
    chatbot_row = MagicMock()
    chatbot_row.id = uuid4()
    chatbot_repo = MagicMock()
    chatbot_repo.get = AsyncMock(return_value=chatbot_row)
    session = MagicMock()

    with pytest.raises(ValidationError, match="cookie"):
        await create_session(
            session, ctx,
            chatbot_repo_factory=lambda s, c: chatbot_repo,
            chatbot_id=chatbot_row.id,
            origin="widget",
            public_session_cookie=None,
        )


@pytest.mark.asyncio
async def test_append_message_validates_session_and_appends() -> None:
    ctx = _ctx()
    s_row = _session_row(tenant_id=ctx.tenant_id)
    session_repo = MagicMock()
    session_repo.get = AsyncMock(return_value=s_row)
    message_repo = MagicMock()
    appended = _message_row(s_row.id)
    message_repo.append = AsyncMock(return_value=appended)
    session = MagicMock()

    result_id = await append_message(
        session, ctx,
        session_repo_factory=lambda s, c: session_repo,
        message_repo_factory=lambda s: message_repo,
        session_id=s_row.id,
        role="user",
        content="hi",
        citations=None,
        metadata=None,
    )

    assert result_id == appended.id
    message_repo.append.assert_awaited_once_with(
        session_id=s_row.id,
        role="user",
        content="hi",
        citations=None,
        metadata=None,
    )


@pytest.mark.asyncio
async def test_append_message_raises_when_session_missing() -> None:
    ctx = _ctx()
    session_repo = MagicMock()
    session_repo.get = AsyncMock(side_effect=NotFoundError("nope"))
    message_repo = MagicMock()
    session = MagicMock()

    with pytest.raises(SessionNotFoundError):
        await append_message(
            session, ctx,
            session_repo_factory=lambda s, c: session_repo,
            message_repo_factory=lambda s: message_repo,
            session_id=uuid4(),
            role="user", content="hi",
            citations=None, metadata=None,
        )


@pytest.mark.asyncio
async def test_touch_session_calls_repo() -> None:
    ctx = _ctx()
    session_repo = MagicMock()
    session_repo.touch = AsyncMock()
    session = MagicMock()
    sid = uuid4()

    await touch_session(
        session, ctx,
        session_repo_factory=lambda s, c: session_repo,
        session_id=sid,
    )

    session_repo.touch.assert_awaited_once_with(sid)
```

- [ ] **Step 3.2: Run, confirm collection failure**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
pytest tests/unit/test_chat_sessions_use_cases.py -v
```

Expected: collection errors — the use case modules don't exist yet.

- [ ] **Step 3.3: Create `backend/src/tfm_rag/application/chat/list_sessions.py`**

```python
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.infrastructure.persistence.repositories.chat_sessions_repo import (
    ChatSessionRepository,
)
from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
    ChatbotRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

ChatbotRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatbotRepository
]
SessionRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatSessionRepository
]


def _default_chatbot_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatbotRepository:
    return ChatbotRepository(session, ctx)


def _default_session_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatSessionRepository:
    return ChatSessionRepository(session, ctx)


@dataclass(frozen=True, slots=True)
class SessionSummaryView:
    id: UUID
    chatbot_id: UUID
    origin: Literal["playground", "widget"]
    created_at: datetime
    last_activity_at: datetime


async def list_sessions(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    chatbot_repo_factory: ChatbotRepoFactory = _default_chatbot_repo,
    session_repo_factory: SessionRepoFactory = _default_session_repo,
    chatbot_id: UUID,
    limit: int = 20,
    offset: int = 0,
) -> list[SessionSummaryView]:
    chatbot_repo = chatbot_repo_factory(session, ctx)
    try:
        await chatbot_repo.get(chatbot_id)
    except NotFoundError as exc:
        raise ChatbotNotFoundError(str(exc)) from exc

    session_repo = session_repo_factory(session, ctx)
    rows = await session_repo.list_by_chatbot(
        chatbot_id=chatbot_id, limit=limit, offset=offset
    )
    return [
        SessionSummaryView(
            id=r.id,
            chatbot_id=r.chatbot_id,
            origin=r.origin,  # type: ignore[arg-type]
            created_at=r.created_at,
            last_activity_at=r.last_activity_at,
        )
        for r in rows
    ]
```

- [ ] **Step 3.4: Create `backend/src/tfm_rag/application/chat/get_session.py`**

```python
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.chat import SessionNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.infrastructure.persistence.repositories.chat_sessions_repo import (
    ChatMessageRepository,
    ChatSessionRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

SessionRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatSessionRepository
]
MessageRepoFactory = Callable[[AsyncSession], ChatMessageRepository]


def _default_session_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatSessionRepository:
    return ChatSessionRepository(session, ctx)


def _default_message_repo(session: AsyncSession) -> ChatMessageRepository:
    return ChatMessageRepository(session)


@dataclass(frozen=True, slots=True)
class SessionView:
    id: UUID
    chatbot_id: UUID
    origin: Literal["playground", "widget"]
    created_at: datetime
    last_activity_at: datetime


@dataclass(frozen=True, slots=True)
class MessageView:
    id: UUID
    session_id: UUID
    role: Literal["user", "assistant", "system"]
    content: str
    citations: list[dict[str, Any]]
    metadata: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SessionDetailView:
    session: SessionView
    messages: list[MessageView]


async def get_session(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    session_repo_factory: SessionRepoFactory = _default_session_repo,
    message_repo_factory: MessageRepoFactory = _default_message_repo,
    session_id: UUID,
) -> SessionDetailView:
    session_repo = session_repo_factory(session, ctx)
    try:
        s_row = await session_repo.get(session_id)
    except NotFoundError as exc:
        raise SessionNotFoundError(str(exc)) from exc

    message_repo = message_repo_factory(session)
    m_rows = await message_repo.list_by_session(session_id)

    return SessionDetailView(
        session=SessionView(
            id=s_row.id,
            chatbot_id=s_row.chatbot_id,
            origin=s_row.origin,  # type: ignore[arg-type]
            created_at=s_row.created_at,
            last_activity_at=s_row.last_activity_at,
        ),
        messages=[
            MessageView(
                id=m.id,
                session_id=m.session_id,
                role=m.role,  # type: ignore[arg-type]
                content=m.content,
                citations=m.citations,
                metadata=m.metadata_,
                created_at=m.created_at,
            )
            for m in m_rows
        ],
    )
```

- [ ] **Step 3.5: Create `backend/src/tfm_rag/application/chat/create_session.py`**

```python
from collections.abc import Callable
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError, ValidationError
from tfm_rag.infrastructure.persistence.models.chat_sessions import (
    ChatSessionRow,
)
from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
    ChatbotRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

ChatbotRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatbotRepository
]


def _default_chatbot_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatbotRepository:
    return ChatbotRepository(session, ctx)


async def create_session(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    chatbot_repo_factory: ChatbotRepoFactory = _default_chatbot_repo,
    chatbot_id: UUID,
    origin: Literal["playground", "widget"],
    public_session_cookie: str | None,
) -> UUID:
    """Internal helper. Plan #15's agent loop calls this to start a session.

    Validates that the chatbot exists in the tenant before creating the
    session row. `widget` origin requires `public_session_cookie`;
    `playground` requires None.
    """
    if origin not in ("playground", "widget"):
        raise ValidationError(f"Unknown session origin: {origin!r}")
    if origin == "widget" and not public_session_cookie:
        raise ValidationError(
            "origin=widget requires a public_session_cookie value"
        )
    if origin == "playground" and public_session_cookie is not None:
        raise ValidationError(
            "origin=playground must not carry a public_session_cookie"
        )

    chatbot_repo = chatbot_repo_factory(session, ctx)
    try:
        await chatbot_repo.get(chatbot_id)
    except NotFoundError as exc:
        raise ChatbotNotFoundError(str(exc)) from exc

    session_id = uuid4()
    row = ChatSessionRow(
        id=session_id,
        chatbot_id=chatbot_id,
        tenant_id=ctx.tenant_id,
        origin=origin,
        public_session_cookie=public_session_cookie,
    )
    session.add(row)
    await session.flush()
    return session_id
```

- [ ] **Step 3.6: Create `backend/src/tfm_rag/application/chat/append_message.py`**

```python
from collections.abc import Callable
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.chat import SessionNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.infrastructure.persistence.repositories.chat_sessions_repo import (
    ChatMessageRepository,
    ChatSessionRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

SessionRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatSessionRepository
]
MessageRepoFactory = Callable[[AsyncSession], ChatMessageRepository]


def _default_session_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatSessionRepository:
    return ChatSessionRepository(session, ctx)


def _default_message_repo(session: AsyncSession) -> ChatMessageRepository:
    return ChatMessageRepository(session)


async def append_message(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    session_repo_factory: SessionRepoFactory = _default_session_repo,
    message_repo_factory: MessageRepoFactory = _default_message_repo,
    session_id: UUID,
    role: Literal["user", "assistant", "system"],
    content: str,
    citations: list[dict[str, Any]] | None,
    metadata: dict[str, Any] | None,
) -> UUID:
    """Internal helper. Plan #15's agent loop calls this per turn."""
    session_repo = session_repo_factory(session, ctx)
    try:
        await session_repo.get(session_id)
    except NotFoundError as exc:
        raise SessionNotFoundError(str(exc)) from exc

    message_repo = message_repo_factory(session)
    row = await message_repo.append(
        session_id=session_id,
        role=role,
        content=content,
        citations=citations,
        metadata=metadata,
    )
    return row.id
```

- [ ] **Step 3.7: Create `backend/src/tfm_rag/application/chat/touch_session.py`**

```python
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.infrastructure.persistence.repositories.chat_sessions_repo import (
    ChatSessionRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

SessionRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatSessionRepository
]


def _default_session_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatSessionRepository:
    return ChatSessionRepository(session, ctx)


async def touch_session(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    session_repo_factory: SessionRepoFactory = _default_session_repo,
    session_id: UUID,
) -> None:
    """Internal helper. Bumps `last_activity_at`. No-op if the session
    doesn't belong to the tenant (defense in depth — the agent loop should
    never call touch on a foreign session, but if it did we silently
    drop the update at the SQL layer via the tenant_id filter).
    """
    session_repo = session_repo_factory(session, ctx)
    await session_repo.touch(session_id)
```

- [ ] **Step 3.8: Run the unit tests, expect 9 PASSED**

```bash
pytest tests/unit/test_chat_sessions_use_cases.py -v
```

Expected: **9 PASSED**.

- [ ] **Step 3.9: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/application/chat/list_sessions.py backend/src/tfm_rag/application/chat/get_session.py backend/src/tfm_rag/application/chat/create_session.py backend/src/tfm_rag/application/chat/append_message.py backend/src/tfm_rag/application/chat/touch_session.py backend/tests/unit/test_chat_sessions_use_cases.py
git commit -m "feat(chat): list/get sessions + internal create/append/touch helpers"
```

---

## Task 4 — API: `GET /api/chatbots/{id}/sessions` + `GET /api/sessions/{id}`

**Files:**
- Modify: `backend/src/tfm_rag/infrastructure/api/routers/chatbots.py` (add `GET /{chatbot_id}/sessions`)
- Create: `backend/src/tfm_rag/infrastructure/api/routers/sessions.py`
- Modify: `backend/src/tfm_rag/infrastructure/api/app.py` (mount the new router)

- [ ] **Step 4.1: Append the sessions list endpoint to `chatbots.py`**

Open `backend/src/tfm_rag/infrastructure/api/routers/chatbots.py`. Merge these imports into the existing import block at the top of the file (do not duplicate):

```python
from tfm_rag.application.chat.list_sessions import (
    SessionSummaryView,
    list_sessions,
)
```

Then add the new request/response model and route at the bottom of the file:

```python
class SessionSummaryOut(BaseModel):
    id: str
    chatbot_id: str
    origin: str
    created_at: str
    last_activity_at: str

    @classmethod
    def from_view(cls, v: SessionSummaryView) -> "SessionSummaryOut":
        return cls(
            id=str(v.id),
            chatbot_id=str(v.chatbot_id),
            origin=v.origin,
            created_at=v.created_at.isoformat(),
            last_activity_at=v.last_activity_at.isoformat(),
        )


@router.get("/{chatbot_id}/sessions", response_model=list[SessionSummaryOut])
async def list_sessions_(
    chatbot_id: UUID,
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> list[SessionSummaryOut]:
    try:
        views = await list_sessions(
            session, ctx,
            chatbot_id=chatbot_id,
            limit=limit, offset=offset,
        )
    except ChatbotNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [SessionSummaryOut.from_view(v) for v in views]
```

- [ ] **Step 4.2: Create `backend/src/tfm_rag/infrastructure/api/routers/sessions.py`**

```python
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
    get_session as get_db_session,
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
        view = await get_session(session, ctx, session_id=session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SessionDetailOut.from_view(view)
```

- [ ] **Step 4.3: Mount the new router in `app.py`**

Replace the existing router-imports block + `include_router` calls inside `create_app`. The final shape should be:

```python
from fastapi import FastAPI

from tfm_rag.infrastructure.api.middleware.tenant_scoping import (
    TenantScopingMiddleware,
)
from tfm_rag.infrastructure.api.routers import (
    auth,
    chatbots,
    credentials,
    health,
    ingestion_jobs,
    knowledge_bases,
    sessions,
)
from tfm_rag.infrastructure.settings import get_settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="TFM RAG Chatbot Platform",
        version="0.1.0",
    )
    settings = get_settings()
    app.add_middleware(TenantScopingMiddleware, settings=settings)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(credentials.router)
    app.include_router(knowledge_bases.router)
    app.include_router(ingestion_jobs.router)
    app.include_router(chatbots.router)
    app.include_router(sessions.router)
    return app


app = create_app()
```

- [ ] **Step 4.4: Verify app imports cleanly**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
python -c "from tfm_rag.infrastructure.api.app import app; print(app.title)"
```

Expected: prints `TFM RAG Chatbot Platform`.

- [ ] **Step 4.5: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/infrastructure/api/routers/chatbots.py backend/src/tfm_rag/infrastructure/api/routers/sessions.py backend/src/tfm_rag/infrastructure/api/app.py
git commit -m "feat(api): GET /api/chatbots/{id}/sessions + GET /api/sessions/{id}"
```

---

## Task 5 — Integration test: seed sessions via helpers + assert read endpoints

This test seeds sessions/messages via the internal helpers (since the
agent loop in plan #15 isn't shipped yet) and exercises both read endpoints.

**Files:**
- Create: `backend/tests/integration/test_chat_sessions_flow.py`

- [ ] **Step 5.1: Write the integration test**

Create `backend/tests/integration/test_chat_sessions_flow.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import tfm_rag.infrastructure.api.dependencies as _deps
from tfm_rag.application.chat.append_message import append_message
from tfm_rag.application.chat.create_session import create_session
from tfm_rag.infrastructure.api.app import app
from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.settings import Settings


@pytest.fixture
async def _clean_state(settings: Settings) -> None:
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    async with factory() as s:
        await s.execute(text(
            "TRUNCATE chat_messages, chat_sessions, "
            "chatbot_knowledge_base, chatbots, ingestion_jobs, "
            "sources, knowledge_bases, provider_credentials, users, tenants "
            "RESTART IDENTITY CASCADE"
        ))
        await s.commit()
    await engine.dispose()
    _deps._session_factory = None


async def _register(client: AsyncClient, email: str) -> tuple[str, str]:
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "correctpassword"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return body["token"], body["tenant_id"]


async def _ollama_cred_id(client: AsyncClient, token: str) -> str:
    r = await client.get(
        "/api/credentials",
        headers={"Authorization": f"Bearer {token}"},
    )
    return next(c for c in r.json() if c["provider_id"] == "ollama")["id"]


async def _create_chatbot(
    client: AsyncClient, token: str, name: str
) -> str:
    cred = await _ollama_cred_id(client, token)
    r = await client.post(
        "/api/chatbots",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": name,
            "system_prompt": "x",
            "llm_selection": {
                "provider_id": "ollama",
                "credential_id": cred,
                "model_id": "llama3.1",
            },
            "kb_ids": [],
            "widget_config": {},
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.integration
async def test_list_and_get_session_after_seeding(
    _clean_state: None, settings: Settings
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, tenant_id_str = await _register(client, "ses-owner@example.com")
        chatbot_id_str = await _create_chatbot(client, token, "Bot")
        h = {"Authorization": f"Bearer {token}"}

        # Seed: open a session and append 3 messages via the internal helpers.
        engine = build_engine(settings.postgres_url)
        factory = build_session_factory(engine)
        from uuid import UUID

        ctx = RequestContext(
            tenant_id=UUID(tenant_id_str),
            user_id=None,
        )
        async with factory() as db:
            session_id = await create_session(
                db, ctx,
                chatbot_id=UUID(chatbot_id_str),
                origin="playground",
                public_session_cookie=None,
            )
            await append_message(
                db, ctx,
                session_id=session_id,
                role="user", content="hello there",
                citations=None, metadata=None,
            )
            await append_message(
                db, ctx,
                session_id=session_id,
                role="assistant", content="hi! how can I help?",
                citations=[
                    {
                        "source_id": "00000000-0000-0000-0000-000000000000",
                        "source_name": "fake.txt",
                        "location": "p1",
                        "chunk_id": "c0",
                        "score": 0.91,
                    }
                ],
                metadata={"iterations": [{"index": 0, "tool": "final_answer"}]},
            )
            await append_message(
                db, ctx,
                session_id=session_id,
                role="user", content="thanks",
                citations=None, metadata=None,
            )
            await db.commit()
        await engine.dispose()

        # List sessions for this chatbot
        r = await client.get(
            f"/api/chatbots/{chatbot_id_str}/sessions", headers=h
        )
        assert r.status_code == 200, r.text
        sessions_list = r.json()
        assert len(sessions_list) == 1
        assert sessions_list[0]["id"] == str(session_id)
        assert sessions_list[0]["origin"] == "playground"

        # Get session detail
        r = await client.get(f"/api/sessions/{session_id}", headers=h)
        assert r.status_code == 200, r.text
        detail = r.json()
        assert detail["session"]["id"] == str(session_id)
        assert len(detail["messages"]) == 3
        # Messages are ordered by created_at ascending — user first, then
        # assistant, then user again.
        assert detail["messages"][0]["role"] == "user"
        assert detail["messages"][0]["content"] == "hello there"
        assert detail["messages"][1]["role"] == "assistant"
        assert detail["messages"][1]["citations"][0]["score"] == 0.91
        assert detail["messages"][1]["metadata"]["iterations"][0]["tool"] == "final_answer"
        assert detail["messages"][2]["role"] == "user"


@pytest.mark.integration
async def test_list_sessions_for_unknown_chatbot_returns_404(
    _clean_state: None,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, _ = await _register(client, "404@example.com")
        h = {"Authorization": f"Bearer {token}"}

        r = await client.get(
            "/api/chatbots/00000000-0000-0000-0000-000000000000/sessions",
            headers=h,
        )
        assert r.status_code == 404


@pytest.mark.integration
async def test_get_session_isolation_between_tenants(
    _clean_state: None, settings: Settings
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        alice_token, alice_tenant = await _register(
            client, "alice-ses@example.com"
        )
        bob_token, _ = await _register(client, "bob-ses@example.com")
        chatbot_id_str = await _create_chatbot(client, alice_token, "AliceBot")

        # Alice opens a session
        from uuid import UUID

        engine = build_engine(settings.postgres_url)
        factory = build_session_factory(engine)
        ctx = RequestContext(
            tenant_id=UUID(alice_tenant), user_id=None
        )
        async with factory() as db:
            session_id = await create_session(
                db, ctx,
                chatbot_id=UUID(chatbot_id_str),
                origin="playground",
                public_session_cookie=None,
            )
            await db.commit()
        await engine.dispose()

        # Bob tries to read it → 404
        r = await client.get(
            f"/api/sessions/{session_id}",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert r.status_code == 404


@pytest.mark.integration
async def test_delete_chatbot_cascades_sessions_and_messages(
    _clean_state: None, settings: Settings
) -> None:
    """Verifies the spec's 'DeleteChatbot cascada sesiones + mensajes'
    is now real (CASCADE FKs added in plan #14).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, tenant_id_str = await _register(client, "casc@example.com")
        chatbot_id_str = await _create_chatbot(client, token, "ToBeDeleted")
        h = {"Authorization": f"Bearer {token}"}

        from uuid import UUID

        engine = build_engine(settings.postgres_url)
        factory = build_session_factory(engine)
        ctx = RequestContext(
            tenant_id=UUID(tenant_id_str), user_id=None
        )
        async with factory() as db:
            session_id = await create_session(
                db, ctx,
                chatbot_id=UUID(chatbot_id_str),
                origin="playground",
                public_session_cookie=None,
            )
            await append_message(
                db, ctx,
                session_id=session_id,
                role="user", content="will be cascaded",
                citations=None, metadata=None,
            )
            await db.commit()
        await engine.dispose()

        # Delete the chatbot
        r = await client.delete(f"/api/chatbots/{chatbot_id_str}", headers=h)
        assert r.status_code == 204

        # Session is gone (cascade)
        r = await client.get(f"/api/sessions/{session_id}", headers=h)
        assert r.status_code == 404
```

- [ ] **Step 5.2: Reset DB and run the integration test**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
docker exec tfm-rag-postgres-1 psql -U tfm -d tfm_rag \
  -c "DROP TABLE IF EXISTS chat_messages, chat_sessions, chatbot_knowledge_base, chatbots, ingestion_jobs, sources, knowledge_bases, provider_credentials, users, tenants, alembic_version CASCADE;"
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
alembic upgrade head
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
pytest tests/integration/test_chat_sessions_flow.py -m integration -v
```

Expected: **4 PASSED**.

- [ ] **Step 5.3: Run the full integration suite to confirm no regressions**

```bash
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
pytest tests/integration -m integration -v
```

Expected: previous 20 + 1 migration + 4 flow = **25 PASSED**.

- [ ] **Step 5.4: Commit + tag**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/tests/integration/test_chat_sessions_flow.py
git commit -m "test(chat): list/get sessions + tenant isolation + chatbot cascade"
git tag cap-14-chat-sessions
```

---

## What's next (deferred, for handover)

After this plan ships:

- **Plan #15 (CAP-CHAT-AGENT-LOOP / AnswerQuery)** is the final piece for M3. It:
  - Adds an LLM port + Ollama adapter (so the chatbot can generate answers).
  - Implements `AnswerQuery(chatbot_id, session_id?, user_message)` — the agent loop. Reuses `retrieve_docs` (plan #12) as the `search_docs` tool. Calls `create_session` (if no session_id), `append_message` for user + assistant turns, `touch_session` per turn.
  - Adds `POST /api/chatbots/{chatbot_id}/chat` — for now returning a non-streaming JSON response. SSE streaming can land in a small follow-up plan; the spec calls for SSE but the demo works fine without it for M3.
  - Defines the typed VOs `Citation` and `RetrievalIteration` (right now they're loose dicts in `chat_messages.citations` / `chat_messages.metadata.iterations`).

After #15 lands, the M3 demo is complete: a user creates a chatbot, attaches the M2 KB, asks a question, and gets a cited answer.
