from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from tfm_rag.application.chatbot_config.create_chatbot import (
    _to_view,
    create_chatbot,
)
from tfm_rag.application.chatbot_config.delete_chatbot import delete_chatbot
from tfm_rag.application.chatbot_config.list_chatbots import list_chatbots
from tfm_rag.application.chatbot_config.update_chatbot import update_chatbot
from tfm_rag.domain.entities.chatbot import Chatbot
from tfm_rag.domain.entities.knowledge_base import KnowledgeBase
from tfm_rag.domain.errors.chatbot import (
    ChatbotAlreadyExistsError,
    ChatbotNotFoundError,
)
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import IncompatibleEmbeddingsError
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.domain.value_objects.role_llm_selections import RoleLLMSelections
from tfm_rag.domain.value_objects.widget_config import WidgetConfig

_NOW = datetime.now(UTC)


def _selection_1024(credential_id: UUID | None = None) -> EmbeddingSelection:
    return EmbeddingSelection(
        credential_id=credential_id or uuid4(),
        model_id="bge-m3",
        dim=1024,
    )


def _selection_768(credential_id: UUID | None = None) -> EmbeddingSelection:
    return EmbeddingSelection(
        credential_id=credential_id or uuid4(),
        model_id="nomic-embed-text",
        dim=768,
    )


def _llm() -> LLMSelection:
    return LLMSelection(credential_id=uuid4(), model_id="llama3.1")


def _kb_entity(selection: EmbeddingSelection) -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid4(),
        tenant_id=uuid4(),
        name="kb",
        description=None,
        chunking_config=ChunkingConfig.default(),
        embedding_selection=selection,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _chatbot(
    *,
    name: str = "bot",
    description: str | None = None,
    system_prompt: str = "old prompt",
    llm_selection: LLMSelection | None = None,
    kb_ids: list[UUID] | None = None,
    public_key: str = "wgt_existing",
) -> Chatbot:
    return Chatbot(
        id=uuid4(),
        tenant_id=uuid4(),
        name=name,
        description=description,
        system_prompt=system_prompt,
        llm_selection=llm_selection or _llm(),
        pipeline_config=PipelineConfig.default(),
        role_llm_selections=RoleLLMSelections.default(),
        widget_config=WidgetConfig.default(),
        public_key=public_key,
        kb_ids=kb_ids or [],
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_to_view_maps_chatbot_entity_fields() -> None:
    chatbot = _chatbot(kb_ids=[uuid4()])
    view = _to_view(chatbot)
    assert view.id == chatbot.id
    assert view.tenant_id == chatbot.tenant_id
    assert view.name == chatbot.name
    assert view.role_llm_selections is chatbot.role_llm_selections
    assert view.llm_selection is chatbot.llm_selection
    assert view.pipeline_config is chatbot.pipeline_config
    assert view.widget_config == chatbot.widget_config.to_dict()
    assert view.kb_ids == chatbot.kb_ids


@pytest.mark.asyncio
async def test_create_chatbot_with_zero_kbs_is_allowed() -> None:
    """Spec Q6.10: chatbots with 0 KBs are valid (LLM puro)."""
    chatbot_repo = MagicMock()
    chatbot_repo.find_chatbot_by_name = AsyncMock(return_value=None)
    created = _chatbot(name="LLM-only bot", kb_ids=[])
    chatbot_repo.create_chatbot = AsyncMock(return_value=created)

    kb_repo = MagicMock()
    kb_repo.get_knowledge_base = AsyncMock()  # never called when kb_ids is empty

    result = await create_chatbot(
        chatbot_repo=chatbot_repo,
        kb_repo=kb_repo,
        name="LLM-only bot",
        description=None,
        system_prompt="Be concise.",
        llm_selection=_llm(),
        kb_ids=[],
        pipeline_config=PipelineConfig.default(),
        widget_config=WidgetConfig.default(),
    )

    assert result.kb_ids == []
    kb_repo.get_knowledge_base.assert_not_called()
    chatbot_repo.create_chatbot.assert_awaited_once()
    assert chatbot_repo.create_chatbot.call_args.kwargs["kb_ids"] == []


@pytest.mark.asyncio
async def test_create_chatbot_with_compatible_kbs_succeeds() -> None:
    selection = _selection_1024()
    kb1, kb2 = _kb_entity(selection), _kb_entity(selection)

    chatbot_repo = MagicMock()
    chatbot_repo.find_chatbot_by_name = AsyncMock(return_value=None)
    created = _chatbot(name="Bot", kb_ids=[kb1.id, kb2.id])
    chatbot_repo.create_chatbot = AsyncMock(return_value=created)

    kb_repo = MagicMock()
    kb_repo.get_knowledge_base = AsyncMock(side_effect=[kb1, kb2])

    result = await create_chatbot(
        chatbot_repo=chatbot_repo,
        kb_repo=kb_repo,
        name="Bot",
        description=None,
        system_prompt="Be concise.",
        llm_selection=_llm(),
        kb_ids=[kb1.id, kb2.id],
        pipeline_config=PipelineConfig.default(),
        widget_config=WidgetConfig.default(),
    )

    assert set(result.kb_ids) == {kb1.id, kb2.id}
    assert chatbot_repo.create_chatbot.call_args.kwargs["kb_ids"] == [kb1.id, kb2.id]


@pytest.mark.asyncio
async def test_create_chatbot_with_incompatible_kbs_rejected() -> None:
    kb_a = _kb_entity(_selection_1024())
    kb_b = _kb_entity(_selection_768())

    chatbot_repo = MagicMock()
    chatbot_repo.find_chatbot_by_name = AsyncMock(return_value=None)

    kb_repo = MagicMock()
    kb_repo.get_knowledge_base = AsyncMock(side_effect=[kb_a, kb_b])

    with pytest.raises(IncompatibleEmbeddingsError):
        await create_chatbot(
            chatbot_repo=chatbot_repo,
            kb_repo=kb_repo,
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

    chatbot_repo = MagicMock()
    chatbot_repo.find_chatbot_by_name = AsyncMock(return_value=None)
    kb_repo = MagicMock()
    kb_repo.get_knowledge_base = AsyncMock(side_effect=NotFoundError("nope"))

    with pytest.raises(KnowledgeBaseNotFoundError):
        await create_chatbot(
            chatbot_repo=chatbot_repo,
            kb_repo=kb_repo,
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
    chatbot_repo = MagicMock()
    chatbot_repo.find_chatbot_by_name = AsyncMock(return_value=_chatbot())
    kb_repo = MagicMock()

    with pytest.raises(ChatbotAlreadyExistsError):
        await create_chatbot(
            chatbot_repo=chatbot_repo,
            kb_repo=kb_repo,
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
    selection = _selection_1024()
    current = _chatbot(name="old", description=None, system_prompt="old prompt")

    chatbot_repo = MagicMock()
    chatbot_repo.get_chatbot = AsyncMock(return_value=current)
    updated = _chatbot(name="new")
    chatbot_repo.update_chatbot = AsyncMock(return_value=updated)

    kb1, kb2 = _kb_entity(selection), _kb_entity(selection)
    kb_repo = MagicMock()
    kb_repo.get_knowledge_base = AsyncMock(side_effect=[kb1, kb2])

    result = await update_chatbot(
        chatbot_repo=chatbot_repo,
        kb_repo=kb_repo,
        chatbot_id=current.id,
        name="new",
        description=None,
        system_prompt=None,
        llm_selection=None,
        kb_ids=[kb1.id, kb2.id],
        pipeline_config=None,
        widget_config=None,
    )

    assert result.name == "new"
    chatbot_repo.update_chatbot.assert_awaited_once()
    kwargs = chatbot_repo.update_chatbot.call_args.kwargs
    assert kwargs["name"] == "new"
    assert kwargs["kb_ids"] == [kb1.id, kb2.id]
    # Untouched fields fall back to the current entity's values.
    assert kwargs["system_prompt"] == current.system_prompt
    assert kwargs["llm_selection"] is current.llm_selection


@pytest.mark.asyncio
async def test_update_chatbot_missing_returns_chatbot_not_found() -> None:
    chatbot_repo = MagicMock()
    chatbot_repo.get_chatbot = AsyncMock(side_effect=NotFoundError("nope"))
    kb_repo = MagicMock()

    with pytest.raises(ChatbotNotFoundError):
        await update_chatbot(
            chatbot_repo=chatbot_repo,
            kb_repo=kb_repo,
            chatbot_id=uuid4(),
            name="x", description=None, system_prompt=None,
            llm_selection=None, kb_ids=None,
            pipeline_config=None, widget_config=None,
        )


@pytest.mark.asyncio
async def test_list_chatbots_uses_pagination() -> None:
    repo = MagicMock()
    repo.list_chatbots = AsyncMock(return_value=[])

    await list_chatbots(chatbot_repo=repo, limit=10, offset=5)

    repo.list_chatbots.assert_awaited_once_with(limit=10, offset=5)


@pytest.mark.asyncio
async def test_delete_chatbot_calls_repo() -> None:
    repo = MagicMock()
    repo.delete_chatbot = AsyncMock()
    chatbot_id = uuid4()

    await delete_chatbot(chatbot_repo=repo, chatbot_id=chatbot_id)

    repo.delete_chatbot.assert_awaited_once_with(chatbot_id)


@pytest.mark.asyncio
async def test_delete_chatbot_missing_raises_chatbot_not_found() -> None:
    repo = MagicMock()
    repo.delete_chatbot = AsyncMock(
        side_effect=ChatbotNotFoundError("Chatbot(...) not found in tenant")
    )

    with pytest.raises(ChatbotNotFoundError):
        await delete_chatbot(chatbot_repo=repo, chatbot_id=uuid4())


@pytest.mark.asyncio
async def test_create_chatbot_generates_public_key() -> None:
    chatbot_repo = MagicMock()
    chatbot_repo.find_chatbot_by_name = AsyncMock(return_value=None)

    async def _fake_create(**kwargs: object) -> Chatbot:
        assert isinstance(kwargs["public_key"], str)
        assert kwargs["public_key"].startswith("wgt_")
        assert len(kwargs["public_key"]) > 10
        return _chatbot(name="PublicKeyBot", public_key=kwargs["public_key"])

    chatbot_repo.create_chatbot = AsyncMock(side_effect=_fake_create)
    kb_repo = MagicMock()

    view = await create_chatbot(
        chatbot_repo=chatbot_repo,
        kb_repo=kb_repo,
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


@pytest.mark.asyncio
async def test_update_chatbot_does_not_touch_public_key() -> None:
    current = _chatbot(public_key="wgt_existing")

    chatbot_repo = MagicMock()
    chatbot_repo.get_chatbot = AsyncMock(return_value=current)
    chatbot_repo.update_chatbot = AsyncMock(
        return_value=_chatbot(public_key="wgt_existing")
    )

    kb_repo = MagicMock()

    result = await update_chatbot(
        chatbot_repo=chatbot_repo,
        kb_repo=kb_repo,
        chatbot_id=current.id,
        name=None,
        description=None,
        system_prompt=None,
        llm_selection=None,
        kb_ids=None,
        pipeline_config=None,
        widget_config=WidgetConfig.default(),
    )

    # update_chatbot's port method never receives/overwrites public_key.
    assert "public_key" not in chatbot_repo.update_chatbot.call_args.kwargs
    assert result.public_key == "wgt_existing"
