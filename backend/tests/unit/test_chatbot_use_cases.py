from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from tfm_rag.application.chatbot_config.create_chatbot import (
    create_chatbot,
)
from tfm_rag.application.chatbot_config.delete_chatbot import delete_chatbot
from tfm_rag.application.chatbot_config.list_chatbots import list_chatbots
from tfm_rag.application.chatbot_config.update_chatbot import update_chatbot
from tfm_rag.domain.errors.chatbot import (
    ChatbotAlreadyExistsError,
    ChatbotNotFoundError,
)
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import IncompatibleEmbeddingsError
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.domain.value_objects.widget_config import WidgetConfig
from tfm_rag.infrastructure.persistence.repository import RequestContext


def _ctx() -> RequestContext:
    return RequestContext(tenant_id=uuid4(), user_id=uuid4())


def _selection_1024(credential_id: UUID | None = None) -> EmbeddingSelection:
    return EmbeddingSelection(
        provider_id="ollama",
        credential_id=credential_id or uuid4(),
        model_id="bge-m3",
        dim=1024,
    )


def _selection_768(credential_id: UUID | None = None) -> EmbeddingSelection:
    return EmbeddingSelection(
        provider_id="ollama",
        credential_id=credential_id or uuid4(),
        model_id="nomic-embed-text",
        dim=768,
    )


def _llm() -> LLMSelection:
    return LLMSelection(
        provider_id="ollama", credential_id=uuid4(), model_id="llama3.1"
    )


def _kb_row(selection: EmbeddingSelection) -> MagicMock:
    row = MagicMock()
    row.id = uuid4()
    row.embedding_selection = selection.to_dict()
    return row


@pytest.mark.asyncio
async def test_create_chatbot_with_zero_kbs_is_allowed() -> None:
    """Spec Q6.10: chatbots with 0 KBs are valid (LLM puro)."""
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    ctx = _ctx()

    chatbot_repo = MagicMock()
    chatbot_repo.find_by_name = AsyncMock(return_value=None)
    chatbot_repo.add = AsyncMock(side_effect=lambda r: r)
    chatbot_repo.replace_kb_links = AsyncMock()

    kb_repo = MagicMock()
    kb_repo.get = AsyncMock()  # never called when kb_ids is empty

    result = await create_chatbot(
        session, ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: kb_repo,
        name="LLM-only bot",
        description=None,
        system_prompt="Be concise.",
        llm_selection=_llm(),
        kb_ids=[],
        pipeline_config=PipelineConfig.default(),
        widget_config=WidgetConfig.default(),
    )

    assert result.kb_ids == []
    kb_repo.get.assert_not_called()
    chatbot_repo.replace_kb_links.assert_awaited_once_with(result.id, [])


@pytest.mark.asyncio
async def test_create_chatbot_with_compatible_kbs_succeeds() -> None:
    session = MagicMock()
    ctx = _ctx()
    selection = _selection_1024()
    kb1, kb2 = _kb_row(selection), _kb_row(selection)

    chatbot_repo = MagicMock()
    chatbot_repo.find_by_name = AsyncMock(return_value=None)
    chatbot_repo.add = AsyncMock(side_effect=lambda r: r)
    chatbot_repo.replace_kb_links = AsyncMock()

    kb_repo = MagicMock()
    kb_repo.get = AsyncMock(side_effect=[kb1, kb2])

    result = await create_chatbot(
        session, ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: kb_repo,
        name="Bot",
        description=None,
        system_prompt="Be concise.",
        llm_selection=_llm(),
        kb_ids=[kb1.id, kb2.id],
        pipeline_config=PipelineConfig.default(),
        widget_config=WidgetConfig.default(),
    )

    assert set(result.kb_ids) == {kb1.id, kb2.id}
    chatbot_repo.replace_kb_links.assert_awaited_once_with(
        result.id, [kb1.id, kb2.id]
    )


@pytest.mark.asyncio
async def test_create_chatbot_with_incompatible_kbs_rejected() -> None:
    session = MagicMock()
    ctx = _ctx()
    kb_a = _kb_row(_selection_1024())
    kb_b = _kb_row(_selection_768())

    chatbot_repo = MagicMock()
    chatbot_repo.find_by_name = AsyncMock(return_value=None)

    kb_repo = MagicMock()
    kb_repo.get = AsyncMock(side_effect=[kb_a, kb_b])

    with pytest.raises(IncompatibleEmbeddingsError):
        await create_chatbot(
            session, ctx,
            chatbot_repo_factory=lambda s, c: chatbot_repo,
            kb_repo_factory=lambda s, c: kb_repo,
            name="Bot",
            description=None,
            system_prompt="x",
            llm_selection=_llm(),
            kb_ids=[kb_a.id, kb_b.id],
            pipeline_config=PipelineConfig.default(),
            widget_config=WidgetConfig.default(),
        )


@pytest.mark.asyncio
async def test_create_chatbot_with_unknown_kb_rejected_as_not_found() -> None:
    from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError

    session = MagicMock()
    ctx = _ctx()
    chatbot_repo = MagicMock()
    chatbot_repo.find_by_name = AsyncMock(return_value=None)
    kb_repo = MagicMock()
    kb_repo.get = AsyncMock(side_effect=NotFoundError("nope"))

    with pytest.raises(KnowledgeBaseNotFoundError):
        await create_chatbot(
            session, ctx,
            chatbot_repo_factory=lambda s, c: chatbot_repo,
            kb_repo_factory=lambda s, c: kb_repo,
            name="Bot",
            description=None,
            system_prompt="x",
            llm_selection=_llm(),
            kb_ids=[uuid4()],
            pipeline_config=PipelineConfig.default(),
            widget_config=WidgetConfig.default(),
        )


@pytest.mark.asyncio
async def test_create_chatbot_duplicate_name_rejected() -> None:
    session = MagicMock()
    ctx = _ctx()
    chatbot_repo = MagicMock()
    chatbot_repo.find_by_name = AsyncMock(return_value=MagicMock(name="row"))
    kb_repo = MagicMock()

    with pytest.raises(ChatbotAlreadyExistsError):
        await create_chatbot(
            session, ctx,
            chatbot_repo_factory=lambda s, c: chatbot_repo,
            kb_repo_factory=lambda s, c: kb_repo,
            name="Bot",
            description=None,
            system_prompt="x",
            llm_selection=_llm(),
            kb_ids=[],
            pipeline_config=PipelineConfig.default(),
            widget_config=WidgetConfig.default(),
        )


@pytest.mark.asyncio
async def test_update_chatbot_changes_kbs_and_revalidates() -> None:
    session = MagicMock()
    session.flush = AsyncMock()
    ctx = _ctx()
    selection = _selection_1024()
    chatbot_row = MagicMock()
    chatbot_row.id = uuid4()
    chatbot_row.tenant_id = ctx.tenant_id
    chatbot_row.name = "old"
    chatbot_row.description = None
    chatbot_row.system_prompt = "old prompt"
    chatbot_row.llm_selection = _llm().to_dict()
    chatbot_row.router_llm_selection = None
    chatbot_row.pipeline_config = PipelineConfig.default().to_dict()
    chatbot_row.widget_config = WidgetConfig.default().to_dict()
    chatbot_row.public_key = "wgt_existing"
    chatbot_row.created_at = None
    chatbot_row.updated_at = None

    chatbot_repo = MagicMock()
    chatbot_repo.get = AsyncMock(return_value=chatbot_row)
    chatbot_repo.list_kb_ids = AsyncMock(return_value=[])
    chatbot_repo.replace_kb_links = AsyncMock()

    kb1, kb2 = _kb_row(selection), _kb_row(selection)
    kb_repo = MagicMock()
    kb_repo.get = AsyncMock(side_effect=[kb1, kb2])

    result = await update_chatbot(
        session, ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: kb_repo,
        chatbot_id=chatbot_row.id,
        name="new",
        description=None,
        system_prompt=None,
        llm_selection=None,
        kb_ids=[kb1.id, kb2.id],
        pipeline_config=None,
        widget_config=None,
    )

    assert result.name == "new"
    chatbot_repo.replace_kb_links.assert_awaited_once_with(
        chatbot_row.id, [kb1.id, kb2.id]
    )


@pytest.mark.asyncio
async def test_update_chatbot_missing_returns_chatbot_not_found() -> None:
    session = MagicMock()
    ctx = _ctx()
    chatbot_repo = MagicMock()
    chatbot_repo.get = AsyncMock(side_effect=NotFoundError("nope"))
    kb_repo = MagicMock()

    with pytest.raises(ChatbotNotFoundError):
        await update_chatbot(
            session, ctx,
            chatbot_repo_factory=lambda s, c: chatbot_repo,
            kb_repo_factory=lambda s, c: kb_repo,
            chatbot_id=uuid4(),
            name="x", description=None, system_prompt=None,
            llm_selection=None, kb_ids=None,
            pipeline_config=None, widget_config=None,
        )


@pytest.mark.asyncio
async def test_list_chatbots_uses_pagination() -> None:
    session = MagicMock()
    ctx = _ctx()
    repo = MagicMock()
    repo.list = AsyncMock(return_value=[])
    repo.list_kb_ids = AsyncMock()  # not called when there are no rows

    await list_chatbots(
        session, ctx,
        chatbot_repo_factory=lambda s, c: repo,
        limit=10, offset=5,
    )

    repo.list.assert_awaited_once_with(limit=10, offset=5)


@pytest.mark.asyncio
async def test_delete_chatbot_calls_repo() -> None:
    session = MagicMock()
    ctx = _ctx()
    repo = MagicMock()
    repo.attempt_delete_with_cascade = AsyncMock()
    chatbot_id = uuid4()

    await delete_chatbot(
        session, ctx,
        chatbot_repo_factory=lambda s, c: repo,
        chatbot_id=chatbot_id,
    )

    repo.attempt_delete_with_cascade.assert_awaited_once_with(chatbot_id)


@pytest.mark.asyncio
async def test_delete_chatbot_missing_raises_chatbot_not_found() -> None:
    from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError

    session = MagicMock()
    ctx = _ctx()
    repo = MagicMock()
    repo.attempt_delete_with_cascade = AsyncMock(
        side_effect=KnowledgeBaseNotFoundError("sentinel")
    )

    with pytest.raises(ChatbotNotFoundError):
        await delete_chatbot(
            session, ctx,
            chatbot_repo_factory=lambda s, c: repo,
            chatbot_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_create_chatbot_generates_public_key() -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    ctx = _ctx()

    chatbot_repo = MagicMock()
    chatbot_repo.find_by_name = AsyncMock(return_value=None)
    chatbot_repo.add = AsyncMock(side_effect=lambda r: r)
    chatbot_repo.replace_kb_links = AsyncMock()

    kb_repo = MagicMock()

    view = await create_chatbot(
        session, ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: kb_repo,
        name="PublicKeyBot",
        description=None,
        system_prompt="Be concise.",
        llm_selection=_llm(),
        kb_ids=[],
        pipeline_config=PipelineConfig.default(),
        widget_config=WidgetConfig.default(),
    )

    assert isinstance(view.public_key, str)
    assert view.public_key.startswith("wgt_")
    assert len(view.public_key) > 10


@pytest.mark.asyncio
async def test_update_chatbot_does_not_touch_public_key() -> None:
    session = MagicMock()
    session.flush = AsyncMock()
    ctx = _ctx()

    chatbot_row = MagicMock()
    chatbot_row.id = uuid4()
    chatbot_row.tenant_id = ctx.tenant_id
    chatbot_row.name = "bot"
    chatbot_row.description = None
    chatbot_row.system_prompt = "prompt"
    chatbot_row.llm_selection = _llm().to_dict()
    chatbot_row.router_llm_selection = None
    chatbot_row.pipeline_config = PipelineConfig.default().to_dict()
    chatbot_row.widget_config = WidgetConfig.default().to_dict()
    chatbot_row.public_key = "wgt_existing"
    chatbot_row.created_at = None
    chatbot_row.updated_at = None

    chatbot_repo = MagicMock()
    chatbot_repo.get = AsyncMock(return_value=chatbot_row)
    chatbot_repo.list_kb_ids = AsyncMock(return_value=[])

    kb_repo = MagicMock()

    await update_chatbot(
        session, ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: kb_repo,
        chatbot_id=chatbot_row.id,
        name=None,
        description=None,
        system_prompt=None,
        llm_selection=None,
        kb_ids=None,
        pipeline_config=None,
        widget_config=WidgetConfig.default(),
    )

    assert chatbot_row.public_key == "wgt_existing"
