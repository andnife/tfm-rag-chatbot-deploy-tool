from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult

from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError
from tfm_rag.infrastructure.persistence.models.chatbot_knowledge_base import (
    ChatbotKnowledgeBaseRow,
)
from tfm_rag.infrastructure.persistence.models.chatbots import ChatbotRow
from tfm_rag.infrastructure.persistence.repository import BaseRepository


class ChatbotRepository(BaseRepository[ChatbotRow]):
    model = ChatbotRow

    async def find_by_name(self, name: str) -> ChatbotRow | None:
        stmt = select(ChatbotRow).where(
            ChatbotRow.tenant_id == self._ctx.tenant_id,
            ChatbotRow.name == name,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_kb_ids(self, chatbot_id: UUID) -> list[UUID]:
        stmt = select(ChatbotKnowledgeBaseRow.kb_id).where(
            ChatbotKnowledgeBaseRow.chatbot_id == chatbot_id,
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def replace_kb_links(
        self, chatbot_id: UUID, kb_ids: list[UUID]
    ) -> None:
        """Replace the set of KBs attached to a chatbot.

        Caller MUST have validated that all kb_ids belong to the tenant and
        share embedding_selection. We delete-all + insert-all rather than
        diff because the chatbot wizard sends the whole set anyway.
        """
        await self._session.execute(
            delete(ChatbotKnowledgeBaseRow).where(
                ChatbotKnowledgeBaseRow.chatbot_id == chatbot_id,
            )
        )
        for kb_id in kb_ids:
            self._session.add(
                ChatbotKnowledgeBaseRow(chatbot_id=chatbot_id, kb_id=kb_id)
            )
        await self._session.flush()

    async def attempt_delete_with_cascade(self, chatbot_id: UUID) -> None:
        """Delete a chatbot. The N:M rows cascade via FK ON DELETE CASCADE on
        chatbot_id. KB rows themselves are NOT touched.
        """
        stmt = delete(ChatbotRow).where(
            ChatbotRow.id == chatbot_id,
            ChatbotRow.tenant_id == self._ctx.tenant_id,
        )
        result: CursorResult[Any] = await self._session.execute(stmt)  # type: ignore[assignment]
        if result.rowcount == 0:
            # Defer to caller; the tenant-aware NotFoundError flow lives in
            # the use case to keep the repo storage-agnostic.
            raise KnowledgeBaseNotFoundError(
                # Sentinel: use case maps this to ChatbotNotFoundError. We
                # reuse the type so we don't import the domain error here
                # — the repo stays in infra and doesn't depend on chatbot
                # errors. Use case translates.
                f"Chatbot row not found: {chatbot_id}"
            )
