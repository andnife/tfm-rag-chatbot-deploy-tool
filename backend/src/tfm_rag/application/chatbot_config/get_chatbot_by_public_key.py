"""get_chatbot_by_public_key — tenant-agnostic chatbot lookup for plan #16.

The widget public chat endpoint has no JWT (no tenant context). It
identifies the bot purely by the URL-embedded `public_key`. This use case
loads the chatbot row by public_key, returning a `ChatbotView` that
includes `tenant_id` so the caller can build a RequestContext for
downstream tenant-scoped queries (sessions, retrieval, etc.).

NO tenant filter is applied; the public_key is the security token here.
The unique constraint on `chatbots.public_key` guarantees ≤1 match.
"""
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.common import DomainError


class PublicKeyNotFoundError(DomainError):
    """Raised when no chatbot row matches the supplied public_key.

    The error message intentionally does NOT include the supplied key —
    that would aid enumeration attacks.
    """


@dataclass(frozen=True, slots=True)
class PublicKeyChatbotView:
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    system_prompt: str
    llm_selection: dict[str, Any]
    pipeline_config: dict[str, Any]
    widget_config: dict[str, Any]
    public_key: str
    kb_ids: list[UUID]


class _ChatbotRepoLike(Protocol):
    async def get_by_public_key(self, public_key: str) -> Any: ...


async def get_chatbot_by_public_key(
    *,
    session: AsyncSession,
    public_key: str,
    chatbot_repo: _ChatbotRepoLike,
) -> PublicKeyChatbotView:
    row = await chatbot_repo.get_by_public_key(public_key)
    if row is None:
        raise PublicKeyNotFoundError("chatbot not found")

    # kb_ids on the row may be a lazy relationship; if the repo populates
    # it (some implementations do), we use it. Otherwise default to [].
    kb_ids = list(getattr(row, "kb_ids", []) or [])

    return PublicKeyChatbotView(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        description=row.description,
        system_prompt=row.system_prompt,
        llm_selection=dict(row.llm_selection or {}),
        pipeline_config=dict(row.pipeline_config or {}),
        widget_config=dict(row.widget_config or {}),
        public_key=row.public_key,
        kb_ids=kb_ids,
    )
