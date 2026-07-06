"""Unit tests for get_chatbot_by_public_key (tenant-agnostic lookup)."""
from uuid import UUID, uuid4

import pytest

from tfm_rag.application.chatbot_config.get_chatbot_by_public_key import (
    PublicKeyNotFoundError,
    get_chatbot_by_public_key,
)

pytestmark = pytest.mark.asyncio


class _FakeRow:
    def __init__(self, *, tenant_id: UUID, public_key: str) -> None:
        self.id = uuid4()
        self.tenant_id = tenant_id
        self.name = "EmbedBot"
        self.description = None
        self.system_prompt = "be helpful"
        self.llm_selection = {
            "credential_id": str(uuid4()),
            "model_id": "llama3.1",
        }
        self.pipeline_config = {"top_k": 3, "max_retrieval_iterations": 3}
        self.widget_config = {"theme": "light"}
        self.public_key = public_key
        self.kb_ids: list[UUID] = []


class _FakeChatbotRepo:
    def __init__(self, rows: dict[str, _FakeRow]) -> None:
        self._rows = rows

    async def get_by_public_key(self, public_key: str) -> _FakeRow | None:
        return self._rows.get(public_key)


async def test_returns_view_when_key_exists() -> None:
    tenant_id = uuid4()
    row = _FakeRow(tenant_id=tenant_id, public_key="wgt_real")
    repo = _FakeChatbotRepo({"wgt_real": row})

    view = await get_chatbot_by_public_key(
        public_key="wgt_real",
        chatbot_repo=repo,  # type: ignore[arg-type]
    )

    assert view.id == row.id
    assert view.tenant_id == tenant_id
    assert view.public_key == "wgt_real"
    # widget_config returns a dict (the API layer reshapes it)
    assert view.widget_config == {"theme": "light"}


async def test_raises_when_key_missing() -> None:
    repo = _FakeChatbotRepo({})
    with pytest.raises(PublicKeyNotFoundError) as exc_info:
        await get_chatbot_by_public_key(
            public_key="wgt_bogus",
            chatbot_repo=repo,  # type: ignore[arg-type]
        )
    # Error message MUST NOT echo the supplied key (defence vs enumeration).
    assert "wgt_bogus" not in str(exc_info.value)


async def test_does_not_filter_by_tenant() -> None:
    """The use case is intentionally tenant-agnostic — the caller derives
    the tenant from the loaded row. Verify by 'creating' a row from one
    tenant and looking it up via the public_key alone (no ctx)."""
    tenant_id = uuid4()
    row = _FakeRow(tenant_id=tenant_id, public_key="wgt_cross")
    repo = _FakeChatbotRepo({"wgt_cross": row})

    view = await get_chatbot_by_public_key(
        public_key="wgt_cross",
        chatbot_repo=repo,  # type: ignore[arg-type]
    )
    assert view.tenant_id == tenant_id
