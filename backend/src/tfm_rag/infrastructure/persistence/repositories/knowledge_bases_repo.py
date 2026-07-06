from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tfm_rag.domain.entities.knowledge_base import KnowledgeBase
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import (
    KnowledgeBaseInUseError,
    KnowledgeBaseNotFoundError,
)
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.model_ref import ModelRef
from tfm_rag.infrastructure.persistence.models.knowledge_bases import (
    KnowledgeBaseRow,
)
from tfm_rag.infrastructure.persistence.repository import BaseRepository


class KnowledgeBaseRepository(BaseRepository[KnowledgeBaseRow]):
    model = KnowledgeBaseRow

    @staticmethod
    def _to_entity(row: KnowledgeBaseRow) -> KnowledgeBase:
        return KnowledgeBase(
            id=row.id,
            tenant_id=row.tenant_id,
            name=row.name,
            description=row.description,
            chunking_config=ChunkingConfig.from_dict(row.chunking_config),
            embedding_selection=EmbeddingSelection.from_dict(
                row.embedding_selection
            ),
            created_at=row.created_at,
            updated_at=row.updated_at,
            description_llm=(
                ModelRef.from_dict(row.description_llm)
                if row.description_llm is not None
                else None
            ),
        )

    async def get_knowledge_base(self, kb_id: UUID) -> KnowledgeBase:
        """Domain-typed read. Raises NotFoundError if missing in the tenant."""
        return self._to_entity(await self.get(kb_id))

    async def find_by_name(self, name: str) -> KnowledgeBase | None:
        stmt = select(KnowledgeBaseRow).where(
            KnowledgeBaseRow.tenant_id == self._ctx.tenant_id,
            KnowledgeBaseRow.name == name,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._to_entity(row) if row is not None else None

    async def list_knowledge_bases(
        self, *, limit: int, offset: int
    ) -> list[KnowledgeBase]:
        return [
            self._to_entity(r)
            for r in await self.list(limit=limit, offset=offset)
        ]

    async def create_knowledge_base(
        self,
        *,
        name: str,
        description: str | None,
        chunking_config: ChunkingConfig,
        embedding_selection: EmbeddingSelection,
        description_llm: ModelRef | None,
    ) -> KnowledgeBase:
        row = KnowledgeBaseRow(
            id=uuid4(),
            tenant_id=self._ctx.tenant_id,
            name=name,
            description=description,
            chunking_config=chunking_config.to_dict(),
            embedding_selection=embedding_selection.to_dict(),
            description_llm=(
                description_llm.to_dict() if description_llm is not None else None
            ),
        )
        await self.add(row)
        await self._session.commit()
        return self._to_entity(row)

    async def update_knowledge_base(
        self,
        kb_id: UUID,
        *,
        name: str,
        description: str | None,
        chunking_config: ChunkingConfig,
        embedding_selection: EmbeddingSelection,
        description_llm: ModelRef | None,
    ) -> KnowledgeBase:
        row = await self.get(kb_id)
        row.name = name
        row.description = description
        row.chunking_config = chunking_config.to_dict()
        row.embedding_selection = embedding_selection.to_dict()
        row.description_llm = (
            description_llm.to_dict() if description_llm is not None else None
        )
        await self._session.flush()
        await self._session.commit()
        return self._to_entity(row)

    async def delete_knowledge_base(self, kb_id: UUID) -> None:
        try:
            await self.delete(kb_id)
            await self._session.commit()
        except NotFoundError as exc:
            raise KnowledgeBaseNotFoundError(str(exc)) from exc
        except IntegrityError as exc:
            # chatbot_knowledge_base FK is RESTRICT: a referenced KB cannot be
            # deleted. Map the DB-layer violation to the domain error.
            raise KnowledgeBaseInUseError(
                f"KnowledgeBase({kb_id}) is referenced by a chatbot"
            ) from exc
