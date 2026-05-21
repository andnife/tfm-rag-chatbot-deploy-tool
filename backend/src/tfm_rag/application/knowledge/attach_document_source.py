from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.common import NotFoundError, ValidationError
from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError
from tfm_rag.domain.ports.storage import Storage
from tfm_rag.infrastructure.persistence.models.sources import SourceRow
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

SUPPORTED_MIME_TYPES: frozenset[str] = frozenset(
    {"application/pdf", "text/plain"}
)

KbRepoFactory = Callable[
    [AsyncSession, RequestContext], KnowledgeBaseRepository
]


def _default_kb_repo(
    session: AsyncSession, ctx: RequestContext
) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session, ctx)


@dataclass(frozen=True, slots=True)
class AttachDocumentResult:
    source_id: UUID
    kb_id: UUID
    filename: str
    mime_type: str
    storage_uri: str


async def attach_document_source(
    session: AsyncSession,
    ctx: RequestContext,
    storage: Storage,
    *,
    kb_repo_factory: KbRepoFactory = _default_kb_repo,
    kb_id: UUID,
    filename: str,
    mime_type: str,
    content: bytes,
) -> AttachDocumentResult:
    if mime_type not in SUPPORTED_MIME_TYPES:
        raise ValidationError(
            f"Unsupported mime_type {mime_type!r}. "
            f"Supported in M2: {sorted(SUPPORTED_MIME_TYPES)}"
        )

    repo = kb_repo_factory(session, ctx)
    try:
        await repo.get(kb_id)
    except NotFoundError as exc:
        raise KnowledgeBaseNotFoundError(str(exc)) from exc

    source_id = uuid4()
    storage_uri = await storage.save(
        tenant_id=ctx.tenant_id,
        source_id=source_id,
        filename=filename,
        content=content,
    )

    row = SourceRow(
        id=source_id,
        kb_id=kb_id,
        type="document",
        payload={
            "kind": "upload",
            "storage_uri": storage_uri,
            "filename": filename,
            "mime_type": mime_type,
            "size_bytes": len(content),
        },
        ingest_status="not_started",
    )
    session.add(row)
    await session.flush()

    return AttachDocumentResult(
        source_id=source_id,
        kb_id=kb_id,
        filename=filename,
        mime_type=mime_type,
        storage_uri=storage_uri,
    )
