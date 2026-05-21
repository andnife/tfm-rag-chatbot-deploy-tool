from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.knowledge.create_knowledge_base import (
    KnowledgeBaseView,
    _to_view,
)
from tfm_rag.domain.errors.common import NotFoundError, ValidationError
from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
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
class UpdateKnowledgeBaseResult:
    kb: KnowledgeBaseView
    reindex_required: bool


async def update_knowledge_base(
    session: AsyncSession,
    ctx: RequestContext,
    qdrant: QdrantStore,
    *,
    repo_factory: KbRepoFactory = _default_repo,
    kb_id: UUID,
    name: str | None,
    description: str | None,
    chunking_config: ChunkingConfig | None,
    embedding_selection: EmbeddingSelection | None,
) -> UpdateKnowledgeBaseResult:
    repo = repo_factory(session, ctx)
    try:
        row = await repo.get(kb_id)
    except NotFoundError as exc:
        raise KnowledgeBaseNotFoundError(str(exc)) from exc

    reindex = False

    if name is not None:
        name = name.strip()
        if not name:
            raise ValidationError("name must not be empty")
        row.name = name
    if description is not None:
        row.description = description or None

    if chunking_config is not None:
        old = ChunkingConfig.from_dict(row.chunking_config)
        if chunking_config != old:
            row.chunking_config = chunking_config.to_dict()
            reindex = True

    if embedding_selection is not None:
        old_sel = EmbeddingSelection.from_dict(row.embedding_selection)
        if embedding_selection != old_sel:
            row.embedding_selection = embedding_selection.to_dict()
            if embedding_selection.dim != old_sel.dim:
                # Provision the new (tenant, dim) collection so plan #8 can
                # reindex into it.
                await qdrant.ensure_collection(
                    ctx.tenant_id, embedding_selection.dim
                )
            reindex = True

    await session.flush()
    return UpdateKnowledgeBaseResult(kb=_to_view(row), reindex_required=reindex)
