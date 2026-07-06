from tfm_rag.application.knowledge.create_knowledge_base import (
    KnowledgeBaseView,
    _to_view,
)
from tfm_rag.domain.ports.repositories import KnowledgeBaseRepositoryPort


async def list_knowledge_bases(
    *,
    kb_repo: KnowledgeBaseRepositoryPort,
    limit: int = 20,
    offset: int = 0,
) -> list[KnowledgeBaseView]:
    kbs = await kb_repo.list_knowledge_bases(limit=limit, offset=offset)
    return [_to_view(kb) for kb in kbs]
