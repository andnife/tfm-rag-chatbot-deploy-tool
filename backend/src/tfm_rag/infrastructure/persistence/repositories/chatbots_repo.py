from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult

from tfm_rag.domain.entities.chatbot import Chatbot
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.domain.value_objects.role_llm_selections import RoleLLMSelections
from tfm_rag.domain.value_objects.widget_config import WidgetConfig
from tfm_rag.infrastructure.persistence.models.chatbot_knowledge_base import (
    ChatbotKnowledgeBaseRow,
)
from tfm_rag.infrastructure.persistence.models.chatbots import ChatbotRow
from tfm_rag.infrastructure.persistence.repository import BaseRepository


class ChatbotRepository(BaseRepository[ChatbotRow]):
    model = ChatbotRow

    @staticmethod
    def _to_entity(row: ChatbotRow, kb_ids: list[UUID]) -> Chatbot:
        return Chatbot(
            id=row.id,
            tenant_id=row.tenant_id,
            name=row.name,
            description=row.description,
            system_prompt=row.system_prompt,
            llm_selection=LLMSelection.from_dict(row.llm_selection),
            pipeline_config=PipelineConfig.from_dict(row.pipeline_config),
            role_llm_selections=RoleLLMSelections.from_dict(
                row.role_llm_selections
            ),
            widget_config=WidgetConfig.from_dict(row.widget_config),
            public_key=row.public_key,
            kb_ids=kb_ids,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def get_chatbot(self, chatbot_id: UUID) -> Chatbot:
        """Domain-typed read: return the `Chatbot` aggregate with kb_ids.

        Raises NotFoundError (via `get`) if missing in the tenant.
        """
        row = await self.get(chatbot_id)
        kb_ids = await self.list_kb_ids(chatbot_id)
        return self._to_entity(row, kb_ids)

    async def chatbot_exists(self, chatbot_id: UUID) -> bool:
        """Lightweight existence check: selects only `id`, tenant-scoped.

        Avoids the JSONB VO parsing (`_to_entity`) and the extra kb-link
        query that `get_chatbot` incurs — for callers that only need to
        validate existence.
        """
        stmt = select(ChatbotRow.id).where(
            ChatbotRow.id == chatbot_id,
            ChatbotRow.tenant_id == self._ctx.tenant_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def find_by_name(self, name: str) -> ChatbotRow | None:
        stmt = select(ChatbotRow).where(
            ChatbotRow.tenant_id == self._ctx.tenant_id,
            ChatbotRow.name == name,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def find_chatbot_by_name(self, name: str) -> Chatbot | None:
        """Domain-typed read. Returns None if no chatbot has this name."""
        row = await self.find_by_name(name)
        if row is None:
            return None
        kb_ids = await self.list_kb_ids(row.id)
        return self._to_entity(row, kb_ids)

    async def list_chatbots(self, *, limit: int, offset: int) -> list[Chatbot]:
        """Domain-typed, paginated read. Batch-fetches kb_ids to avoid N+1."""
        rows = await self.list(limit=limit, offset=offset)
        if not rows:
            return []
        kb_ids_map = await self.list_kb_ids_batch([r.id for r in rows])
        return [self._to_entity(r, kb_ids_map.get(r.id, [])) for r in rows]

    async def create_chatbot(
        self,
        *,
        name: str,
        description: str | None,
        system_prompt: str,
        llm_selection: LLMSelection,
        role_llm_selections: RoleLLMSelections,
        pipeline_config: PipelineConfig,
        widget_config: WidgetConfig,
        public_key: str,
        kb_ids: list[UUID],
    ) -> Chatbot:
        """Persist a new chatbot + its KB links and commit both atomically."""
        row = ChatbotRow(
            id=uuid4(),
            tenant_id=self._ctx.tenant_id,
            name=name,
            description=description,
            system_prompt=system_prompt,
            llm_selection=llm_selection.to_dict(),
            role_llm_selections=role_llm_selections.to_dict(),
            pipeline_config=pipeline_config.to_dict(),
            widget_config=widget_config.to_dict(),
            public_key=public_key,
        )
        await self.add(row)
        await self.replace_kb_links(row.id, kb_ids)
        await self._session.commit()
        return self._to_entity(row, kb_ids)

    async def update_chatbot(
        self,
        chatbot_id: UUID,
        *,
        name: str,
        description: str | None,
        system_prompt: str,
        llm_selection: LLMSelection,
        role_llm_selections: RoleLLMSelections,
        pipeline_config: PipelineConfig,
        widget_config: WidgetConfig,
        kb_ids: list[UUID] | None,
    ) -> Chatbot:
        """Overwrite the chatbot's mutable scalar fields, optionally replace
        the KB links, and commit both atomically."""
        row = await self.get(chatbot_id)
        row.name = name
        row.description = description
        row.system_prompt = system_prompt
        row.llm_selection = llm_selection.to_dict()
        row.role_llm_selections = role_llm_selections.to_dict()
        row.pipeline_config = pipeline_config.to_dict()
        row.widget_config = widget_config.to_dict()
        await self._session.flush()

        if kb_ids is not None:
            await self.replace_kb_links(chatbot_id, kb_ids)
            final_kb_ids = kb_ids
        else:
            final_kb_ids = await self.list_kb_ids(chatbot_id)

        # The UPDATE fires the server-side `onupdate` on `updated_at`, which
        # leaves the attribute EXPIRED (its new value is DB-generated and not
        # returned by the UPDATE). Reloading it lazily during `_to_entity`
        # would attempt implicit IO outside the async greenlet and raise
        # MissingGreenlet. Refresh it explicitly (awaited) inside the open
        # transaction so the later attribute read is a plain in-memory access.
        # (INSERT populates it via RETURNING, so create_chatbot needs no refresh.)
        await self._session.refresh(row, attribute_names=["updated_at"])

        await self._session.commit()
        return self._to_entity(row, final_kb_ids)

    async def delete_chatbot(self, chatbot_id: UUID) -> None:
        """Delete the chatbot (KB links cascade) and commit."""
        try:
            await self.attempt_delete_with_cascade(chatbot_id)
        except KnowledgeBaseNotFoundError as exc:
            raise ChatbotNotFoundError(
                f"Chatbot({chatbot_id}) not found in tenant"
            ) from exc
        await self._session.commit()

    async def get_by_public_key(self, public_key: str) -> ChatbotRow | None:
        """Look up a chatbot by its widget public key.

        Returns None if not found. Does NOT filter by tenant — the caller
        derives the tenant from the row's `tenant_id` afterwards (plan #16
        public chat endpoint uses this to bootstrap a tenant-scoped session).
        """
        stmt = select(ChatbotRow).where(
            ChatbotRow.public_key == public_key
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_kb_ids(self, chatbot_id: UUID) -> list[UUID]:
        stmt = select(ChatbotKnowledgeBaseRow.kb_id).where(
            ChatbotKnowledgeBaseRow.chatbot_id == chatbot_id,
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_kb_ids_batch(
        self, chatbot_ids: list[UUID]
    ) -> dict[UUID, list[UUID]]:
        """Return {chatbot_id: [kb_ids]} for multiple chatbots in one query."""
        if not chatbot_ids:
            return {}
        stmt = select(ChatbotKnowledgeBaseRow).where(
            ChatbotKnowledgeBaseRow.chatbot_id.in_(chatbot_ids),
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        result: dict[UUID, list[UUID]] = {cid: [] for cid in chatbot_ids}
        for row in rows:
            result[row.chatbot_id].append(row.kb_id)
        return result

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
