from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tfm_rag.application.knowledge.create_knowledge_base import (
    KnowledgeBaseView,
    _to_view,
)
from tfm_rag.domain.entities.source import IngestStatus, Source, SourceType
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError
from tfm_rag.domain.ports.repositories import (
    KnowledgeBaseRepositoryPort,
    SourceRepositoryPort,
)


@dataclass(frozen=True, slots=True)
class SourceView:
    id: UUID
    kb_id: UUID
    type: SourceType
    ingest_status: IngestStatus
    filename: str | None
    error: str | None
    description: str | None
    last_ingest_at: datetime | None


def _src_view(src: Source) -> SourceView:
    payload = src.payload or {}
    if src.type == "document":
        filename = payload.get("filename")
    else:
        # For database sources, synthesize a readable label.
        host = payload.get("host") or "?"
        db = payload.get("db_name") or "?"
        driver = payload.get("driver") or "?"
        filename = f"{driver}://{host}/{db}"
    return SourceView(
        id=src.id,
        kb_id=src.kb_id,
        type=src.type,
        ingest_status=src.ingest_status,
        filename=filename if isinstance(filename, str) else None,
        error=src.error,
        description=src.description,
        last_ingest_at=src.last_ingest_at,
    )


@dataclass(frozen=True, slots=True)
class KnowledgeBaseDetailView:
    kb: KnowledgeBaseView
    sources: list[SourceView]


async def get_knowledge_base(
    *,
    kb_repo: KnowledgeBaseRepositoryPort,
    sources_repo: SourceRepositoryPort,
    kb_id: UUID,
) -> KnowledgeBaseDetailView:
    try:
        kb = await kb_repo.get_knowledge_base(kb_id)
    except NotFoundError as exc:
        raise KnowledgeBaseNotFoundError(str(exc)) from exc
    sources = await sources_repo.list_sources_by_kb(kb_id)
    return KnowledgeBaseDetailView(
        kb=_to_view(kb),
        sources=[_src_view(s) for s in sources],
    )
