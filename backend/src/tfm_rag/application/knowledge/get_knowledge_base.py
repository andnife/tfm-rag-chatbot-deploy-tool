from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.knowledge.create_knowledge_base import (
    KnowledgeBaseView,
    _to_view,
)
from tfm_rag.domain.entities.source import IngestStatus, SourceType
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError
from tfm_rag.infrastructure.persistence.models.sources import SourceRow
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repositories.sources_repo import (
    SourceRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

KbRepoFactory = Callable[
    [AsyncSession, RequestContext], KnowledgeBaseRepository
]
SrcRepoFactory = Callable[[AsyncSession], SourceRepository]


def _default_kb_repo(
    session: AsyncSession, ctx: RequestContext
) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session, ctx)


def _default_src_repo(session: AsyncSession) -> SourceRepository:
    return SourceRepository(session)


@dataclass(frozen=True, slots=True)
class SourceView:
    id: UUID
    kb_id: UUID
    type: SourceType
    ingest_status: IngestStatus


def _src_view(row: SourceRow) -> SourceView:
    return SourceView(
        id=row.id,
        kb_id=row.kb_id,
        type=row.type,  # type: ignore[arg-type]
        ingest_status=row.ingest_status,  # type: ignore[arg-type]
    )


@dataclass(frozen=True, slots=True)
class KnowledgeBaseDetailView:
    kb: KnowledgeBaseView
    sources: list[SourceView]


async def get_knowledge_base(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    kb_repo_factory: KbRepoFactory = _default_kb_repo,
    sources_repo_factory: SrcRepoFactory = _default_src_repo,
    kb_id: UUID,
) -> KnowledgeBaseDetailView:
    kb_repo = kb_repo_factory(session, ctx)
    try:
        kb_row = await kb_repo.get(kb_id)
    except NotFoundError as exc:
        raise KnowledgeBaseNotFoundError(str(exc)) from exc
    src_repo = sources_repo_factory(session)
    src_rows = await src_repo.list_by_kb(kb_id)
    return KnowledgeBaseDetailView(
        kb=_to_view(kb_row),
        sources=[_src_view(r) for r in src_rows],
    )
