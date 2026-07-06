from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tfm_rag.application.chat.append_message import append_message
from tfm_rag.application.chat.create_session import create_session
from tfm_rag.application.chat.get_session import get_session
from tfm_rag.application.chat.list_sessions import list_sessions
from tfm_rag.application.chat.touch_session import touch_session
from tfm_rag.domain.entities.chat_message import ChatMessage
from tfm_rag.domain.entities.chat_session import ChatSession
from tfm_rag.domain.errors.chat import SessionNotFoundError
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError


def _session_entity(session_id=None, chatbot_id=None, tenant_id=None) -> ChatSession:
    return ChatSession(
        id=session_id or uuid4(),
        chatbot_id=chatbot_id or uuid4(),
        tenant_id=tenant_id or uuid4(),
        origin="playground",
        public_session_cookie=None,
        created_at=datetime.now(UTC),
        last_activity_at=datetime.now(UTC),
    )


def _message_entity(session_id) -> ChatMessage:
    return ChatMessage(
        id=uuid4(),
        session_id=session_id,
        role="user",
        content="hello",
        citations=[],
        metadata={},
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_list_sessions_validates_chatbot_and_lists() -> None:
    chatbot_id = uuid4()
    chatbot_repo = MagicMock()
    chatbot_repo.chatbot_exists = AsyncMock(return_value=True)

    session_repo = MagicMock()
    session_repo.list_chat_sessions_by_chatbot = AsyncMock(
        return_value=[_session_entity(chatbot_id=chatbot_id)]
    )

    views = await list_sessions(
        chatbot_repo=chatbot_repo,
        session_repo=session_repo,
        chatbot_id=chatbot_id,
        limit=10, offset=0,
    )

    chatbot_repo.chatbot_exists.assert_awaited_once_with(chatbot_id)
    session_repo.list_chat_sessions_by_chatbot.assert_awaited_once_with(
        chatbot_id=chatbot_id, limit=10, offset=0
    )
    assert len(views) == 1


@pytest.mark.asyncio
async def test_list_sessions_raises_when_chatbot_missing() -> None:
    chatbot_repo = MagicMock()
    chatbot_repo.chatbot_exists = AsyncMock(return_value=False)
    session_repo = MagicMock()

    with pytest.raises(ChatbotNotFoundError):
        await list_sessions(
            chatbot_repo=chatbot_repo,
            session_repo=session_repo,
            chatbot_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_get_session_returns_session_with_messages() -> None:
    s = _session_entity()
    m_a = _message_entity(s.id)
    m_b = _message_entity(s.id)
    session_repo = MagicMock()
    session_repo.get_chat_session = AsyncMock(return_value=s)
    message_repo = MagicMock()
    message_repo.list_messages_by_session = AsyncMock(return_value=[m_a, m_b])

    detail = await get_session(
        session_repo=session_repo,
        message_repo=message_repo,
        session_id=s.id,
    )

    assert detail.session.id == s.id
    assert len(detail.messages) == 2
    message_repo.list_messages_by_session.assert_awaited_once_with(s.id)


@pytest.mark.asyncio
async def test_get_session_raises_when_missing() -> None:
    session_repo = MagicMock()
    session_repo.get_chat_session = AsyncMock(side_effect=NotFoundError("nope"))
    message_repo = MagicMock()

    with pytest.raises(SessionNotFoundError):
        await get_session(
            session_repo=session_repo,
            message_repo=message_repo,
            session_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_create_session_validates_chatbot_and_persists() -> None:
    chatbot_id = uuid4()
    chatbot_repo = MagicMock()
    chatbot_repo.chatbot_exists = AsyncMock(return_value=True)

    new_id = uuid4()
    session_repo = MagicMock()
    session_repo.create_chat_session = AsyncMock(return_value=new_id)

    session_id = await create_session(
        chatbot_repo=chatbot_repo,
        session_repo=session_repo,
        chatbot_id=chatbot_id,
        origin="playground",
        public_session_cookie=None,
    )

    assert session_id == new_id
    chatbot_repo.chatbot_exists.assert_awaited_once_with(chatbot_id)
    session_repo.create_chat_session.assert_awaited_once_with(
        chatbot_id=chatbot_id,
        origin="playground",
        public_session_cookie=None,
    )


@pytest.mark.asyncio
async def test_create_session_raises_when_chatbot_missing() -> None:
    chatbot_repo = MagicMock()
    chatbot_repo.chatbot_exists = AsyncMock(return_value=False)
    session_repo = MagicMock()
    session_repo.create_chat_session = AsyncMock()

    with pytest.raises(ChatbotNotFoundError):
        await create_session(
            chatbot_repo=chatbot_repo,
            session_repo=session_repo,
            chatbot_id=uuid4(),
            origin="playground",
            public_session_cookie=None,
        )
    session_repo.create_chat_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_session_rejects_widget_without_cookie() -> None:
    """origin=widget requires a public_session_cookie (plan #16 sets it)."""
    from tfm_rag.domain.errors.common import ValidationError

    chatbot_repo = MagicMock()
    chatbot_repo.chatbot_exists = AsyncMock(return_value=True)
    session_repo = MagicMock()
    session_repo.create_chat_session = AsyncMock()

    with pytest.raises(ValidationError, match="cookie"):
        await create_session(
            chatbot_repo=chatbot_repo,
            session_repo=session_repo,
            chatbot_id=uuid4(),
            origin="widget",
            public_session_cookie=None,
        )
    session_repo.create_chat_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_append_message_validates_session_and_appends() -> None:
    s = _session_entity()
    session_repo = MagicMock()
    session_repo.get_chat_session = AsyncMock(return_value=s)
    message_repo = MagicMock()
    appended = _message_entity(s.id)
    message_repo.append_message = AsyncMock(return_value=appended)

    result_id = await append_message(
        session_repo=session_repo,
        message_repo=message_repo,
        session_id=s.id,
        role="user",
        content="hi",
        citations=None,
        metadata=None,
    )

    assert result_id == appended.id
    message_repo.append_message.assert_awaited_once_with(
        session_id=s.id,
        role="user",
        content="hi",
        citations=None,
        metadata=None,
    )


@pytest.mark.asyncio
async def test_append_message_raises_when_session_missing() -> None:
    session_repo = MagicMock()
    session_repo.get_chat_session = AsyncMock(side_effect=NotFoundError("nope"))
    message_repo = MagicMock()

    with pytest.raises(SessionNotFoundError):
        await append_message(
            session_repo=session_repo,
            message_repo=message_repo,
            session_id=uuid4(),
            role="user", content="hi",
            citations=None, metadata=None,
        )


@pytest.mark.asyncio
async def test_touch_session_calls_repo() -> None:
    session_repo = MagicMock()
    session_repo.touch = AsyncMock()
    sid = uuid4()

    await touch_session(session_repo=session_repo, session_id=sid)

    session_repo.touch.assert_awaited_once_with(sid)
