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
