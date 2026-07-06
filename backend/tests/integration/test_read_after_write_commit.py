from uuid import uuid4

import pytest

from tfm_rag.application.chatbot_config.create_chatbot import create_chatbot
from tfm_rag.application.chatbot_config.delete_chatbot import delete_chatbot
from tfm_rag.application.chatbot_config.update_chatbot import update_chatbot
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.domain.value_objects.widget_config import WidgetConfig
from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.persistence.models.tenants import TenantRow
from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
    ChatbotRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.settings import Settings


def _llm() -> LLMSelection:
    return LLMSelection(
        credential_id=uuid4(), model_id="llama3.1"
    )


async def _make_tenant(factory, tenant_id) -> None:
    """Insert the tenant row chatbots FK-references (committed in setup)."""
    async with factory() as s:
        s.add(
            TenantRow(
                id=tenant_id,
                name=f"t-{tenant_id}",
                qdrant_collection_prefix=f"kb_chunks__{tenant_id}",
                storage_prefix=f"tenant_{tenant_id}/",
            )
        )
        await s.commit()


async def _make_chatbot(factory, ctx, name: str):
    """Create a chatbot and commit it explicitly, isolated from the fix."""
    async with factory() as s:
        view = await create_chatbot(
            s, ctx,
            name=name, description=None, system_prompt="Be concise.",
            llm_selection=_llm(), kb_ids=[],
            pipeline_config=PipelineConfig.default(),
            widget_config=WidgetConfig.default(),
        )
        # create_chatbot commits internally after the fix.
        return view.id


@pytest.mark.integration
async def test_update_chatbot_visible_to_separate_session(
    settings: Settings,
) -> None:
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    ctx = RequestContext(tenant_id=uuid4(), user_id=uuid4())
    await _make_tenant(factory, ctx.tenant_id)
    chatbot_id = await _make_chatbot(factory, ctx, f"raw-{uuid4().hex[:8]}")

    # Writer session: update the name but DO NOT commit externally.
    async with factory() as writer:
        await update_chatbot(
            writer, ctx,
            chatbot_id=chatbot_id, name="Renamed",
            description=None, system_prompt=None,
            llm_selection=None, kb_ids=None,
            pipeline_config=None, widget_config=None,
        )
        # Reader on a SEPARATE connection must see the new name.
        async with factory() as reader:
            row = await ChatbotRepository(reader, ctx).get(chatbot_id)
            assert row.name == "Renamed"

    await engine.dispose()


@pytest.mark.integration
async def test_create_chatbot_visible_to_separate_session(
    settings: Settings,
) -> None:
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    ctx = RequestContext(tenant_id=uuid4(), user_id=uuid4())
    await _make_tenant(factory, ctx.tenant_id)
    chatbot_id = await _make_chatbot(factory, ctx, f"raw-{uuid4().hex[:8]}")
    async with factory() as reader:
        row = await ChatbotRepository(reader, ctx).get(chatbot_id)
        assert row.id == chatbot_id
    await engine.dispose()


@pytest.mark.integration
async def test_delete_chatbot_visible_to_separate_session(
    settings: Settings,
) -> None:
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    ctx = RequestContext(tenant_id=uuid4(), user_id=uuid4())
    await _make_tenant(factory, ctx.tenant_id)
    chatbot_id = await _make_chatbot(factory, ctx, f"raw-{uuid4().hex[:8]}")
    async with factory() as writer:
        await delete_chatbot(writer, ctx, chatbot_id=chatbot_id)
        async with factory() as reader:
            with pytest.raises(NotFoundError):
                await ChatbotRepository(reader, ctx).get(chatbot_id)
    await engine.dispose()
