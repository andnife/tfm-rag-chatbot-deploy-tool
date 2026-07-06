from uuid import UUID

from tfm_rag.application.knowledge.get_knowledge_base import (
    SourceView,
    _src_view,
)
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError
from tfm_rag.domain.ports.repositories import (
    KnowledgeBaseRepositoryPort,
    SourceRepositoryPort,
)


async def list_sources(
    *,
    kb_repo: KnowledgeBaseRepositoryPort,
    sources_repo: SourceRepositoryPort,
    kb_id: UUID,
) -> list[SourceView]:
    try:
        await kb_repo.get_knowledge_base(kb_id)
    except NotFoundError as exc:
        raise KnowledgeBaseNotFoundError(str(exc)) from exc
    sources = await sources_repo.list_sources_by_kb(kb_id)
    return [_src_view(s) for s in sources]
