"""Unit tests for the suggest_welcome_messages orchestrator (P0.2, unit 3)."""
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from tfm_rag.application.chatbot_config.generate_welcome_messages import (
    WelcomeMessages,
)
from tfm_rag.application.chatbot_config.suggest_welcome_messages import (
    suggest_welcome_messages,
)
from tfm_rag.domain.entities.chatbot import Chatbot
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.domain.value_objects.role_llm_selections import RoleLLMSelections
from tfm_rag.domain.value_objects.widget_config import WidgetConfig

_NOW = datetime.now(UTC)


class _AsyncReturn:
    def __init__(self, value: object) -> None:
        self._value = value

    async def __call__(self, *a: object, **k: object) -> object:
        return self._value


def _chatbot(*, system_prompt: str, kb_ids: list) -> Chatbot:
    return Chatbot(
        id=uuid4(),
        tenant_id=uuid4(),
        name="bot",
        description=None,
        system_prompt=system_prompt,
        llm_selection=LLMSelection(credential_id=uuid4(), model_id="llama3.1"),
        pipeline_config=PipelineConfig.default(),
        role_llm_selections=RoleLLMSelections.default(),
        widget_config=WidgetConfig.default(),
        public_key="wgt_x",
        kb_ids=kb_ids,
        created_at=_NOW,
        updated_at=_NOW,
    )


class _Obj:
    def __init__(self, **kw: object) -> None:
        self.__dict__.update(kw)


@pytest.mark.asyncio
async def test_assembles_kb_summaries_and_forwards_to_generate() -> None:
    kb1, kb2 = uuid4(), uuid4()
    chatbot = _chatbot(system_prompt="Eres el asistente.", kb_ids=[kb1, kb2])

    chatbot_repo = _Obj(get_chatbot=_AsyncReturn(chatbot))
    kb_rows = {
        kb1: _Obj(name="Catálogo", description="Productos y precios"),
        kb2: _Obj(name="FAQ", description=None),
    }

    class _KbRepo:
        async def get_knowledge_base(self, kb_id: object) -> object:
            return kb_rows[kb_id]

    captured: dict[str, object] = {}

    async def fake_generate(**kwargs: object) -> WelcomeMessages:
        captured.update(kwargs)
        return WelcomeMessages("anon", "{name} hi")

    out = await suggest_welcome_messages(
        chatbot_repo=chatbot_repo,
        kb_repo=_KbRepo(),
        credentials_repo=_Obj(),
        llm_dispatcher=_Obj(for_provider=lambda pid: _Obj()),
        encryptor=_Obj(),
        ollama_base_url="http://x",
        chatbot_id=uuid4(),
        resolve_endpoint_fn=_AsyncReturn(("ollama", "http://x", None)),
        generate_fn=fake_generate,
    )

    assert out == WelcomeMessages("anon", "{name} hi")
    assert captured["system_prompt"] == "Eres el asistente."
    summaries = captured["kb_summaries"]
    assert "Catálogo: Productos y precios" in summaries  # name + description
    assert "FAQ" in summaries  # name only when no description


@pytest.mark.asyncio
async def test_chatbot_not_found_raises() -> None:
    class _Repo:
        async def get_chatbot(self, _id: object) -> object:
            raise NotFoundError("nope")

    with pytest.raises(ChatbotNotFoundError):
        await suggest_welcome_messages(
            chatbot_repo=_Repo(),
            kb_repo=_Obj(),
            credentials_repo=_Obj(),
            llm_dispatcher=_Obj(for_provider=lambda pid: _Obj()),
            encryptor=_Obj(),
            ollama_base_url="http://x",
            chatbot_id=uuid4(),
            resolve_endpoint_fn=_AsyncReturn(("ollama", "http://x", None)),
            generate_fn=_AsyncReturn(WelcomeMessages("a", "{name}")),
        )
