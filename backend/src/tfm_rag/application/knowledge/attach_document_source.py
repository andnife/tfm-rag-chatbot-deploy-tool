from dataclasses import dataclass
from uuid import UUID, uuid4

from tfm_rag.domain.errors.common import NotFoundError, ValidationError
from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError
from tfm_rag.domain.ports.repositories import (
    KnowledgeBaseRepositoryPort,
    SourceRepositoryPort,
)
from tfm_rag.domain.ports.storage import Storage

SUPPORTED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "text/plain",
        # CAP-18 OE-2 loaders
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/csv",
        "text/markdown",
    }
)


@dataclass(frozen=True, slots=True)
class AttachDocumentResult:
    source_id: UUID
    kb_id: UUID
    filename: str
    mime_type: str
    storage_uri: str


async def attach_document_source(
    *,
    kb_repo: KnowledgeBaseRepositoryPort,
    sources_repo: SourceRepositoryPort,
    storage: Storage,
    tenant_id: UUID,
    kb_id: UUID,
    filename: str,
    mime_type: str,
    content: bytes,
) -> AttachDocumentResult:
    if mime_type not in SUPPORTED_MIME_TYPES:
        raise ValidationError(
            f"Unsupported mime_type {mime_type!r}. "
            f"Supported: {sorted(SUPPORTED_MIME_TYPES)}"
        )

    try:
        await kb_repo.get_knowledge_base(kb_id)
    except NotFoundError as exc:
        raise KnowledgeBaseNotFoundError(str(exc)) from exc

    source_id = uuid4()
    storage_uri = await storage.save(
        tenant_id=tenant_id,
        source_id=source_id,
        filename=filename,
        content=content,
    )

    await sources_repo.insert_document_source(
        source_id=source_id,
        kb_id=kb_id,
        storage_uri=storage_uri,
        filename=filename,
        mime_type=mime_type,
        size_bytes=len(content),
    )

    return AttachDocumentResult(
        source_id=source_id,
        kb_id=kb_id,
        filename=filename,
        mime_type=mime_type,
        storage_uri=storage_uri,
    )
