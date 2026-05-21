from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.infrastructure.persistence.models.knowledge_bases import (
    KnowledgeBaseRow,
)
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore

KbRepoFactory = Callable[
    [AsyncSession, RequestContext], KnowledgeBaseRepository
]


def _default_repo(
    session: AsyncSession, ctx: RequestContext
) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session, ctx)


@dataclass(frozen=True, slots=True)
class KnowledgeBaseView:
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    chunking_config: ChunkingConfig
    embedding_selection: EmbeddingSelection


def _to_view(row: KnowledgeBaseRow) -> KnowledgeBaseView:
    return KnowledgeBaseView(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        description=row.description,
        chunking_config=ChunkingConfig.from_dict(row.chunking_config),
        embedding_selection=EmbeddingSelection.from_dict(row.embedding_selection),
    )


async def create_knowledge_base(
    session: AsyncSession,
    ctx: RequestContext,
    qdrant: QdrantStore,
    *,
    repo_factory: KbRepoFactory = _default_repo,
    name: str,
    description: str | None,
    chunking_config: ChunkingConfig,
    embedding_selection: EmbeddingSelection,
) -> KnowledgeBaseView:
    name = name.strip()
    if not name:
        raise ValidationError("name must not be empty")
    repo = repo_factory(session, ctx)
    if await repo.find_by_name(name) is not None:
        raise ValidationError(f"KnowledgeBase named {name!r} already exists in tenant")

    # Provision the Qdrant collection for the chosen embedding dim before
    # persisting the KB row, so downstream ingestion (plan #8) can rely on it.
    await qdrant.ensure_collection(ctx.tenant_id, embedding_selection.dim)

    row = KnowledgeBaseRow(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        name=name,
        description=description,
        chunking_config=chunking_config.to_dict(),
        embedding_selection=embedding_selection.to_dict(),
    )
    await repo.add(row)
    return _to_view(row)
