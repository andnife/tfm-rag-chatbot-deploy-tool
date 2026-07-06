"""Unit tests for attach_document_source use case."""
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from tfm_rag.application.knowledge.attach_document_source import (
    AttachDocumentResult,
    attach_document_source,
)
from tfm_rag.domain.entities.knowledge_base import KnowledgeBase
from tfm_rag.domain.errors.common import NotFoundError, ValidationError
from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)


class _FakeKbRepo:
    def __init__(self, kb: KnowledgeBase | None) -> None:
        self._kb = kb
        self.calls: list[UUID] = []

    async def get_knowledge_base(self, kb_id: UUID) -> KnowledgeBase:
        self.calls.append(kb_id)
        if self._kb is None:
            raise NotFoundError(str(kb_id))
        return self._kb


class _FakeSourcesRepo:
    def __init__(self) -> None:
        self.inserted: list[dict[str, Any]] = []

    async def insert_document_source(
        self,
        *,
        source_id: UUID,
        kb_id: UUID,
        storage_uri: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
    ) -> None:
        self.inserted.append(
            {
                "source_id": source_id,
                "kb_id": kb_id,
                "storage_uri": storage_uri,
                "filename": filename,
                "mime_type": mime_type,
                "size_bytes": size_bytes,
            }
        )


class _FakeStorage:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    async def save(
        self, *, tenant_id: UUID, source_id: UUID, filename: str, content: bytes
    ) -> str:
        self.saved.append(
            {
                "tenant_id": tenant_id,
                "source_id": source_id,
                "filename": filename,
                "content": content,
            }
        )
        return f"local://{tenant_id}/{source_id}/{filename}"

    async def load(self, storage_uri: str) -> bytes:
        raise NotImplementedError

    async def delete(self, storage_uri: str) -> None:
        raise NotImplementedError


def _kb(kb_id: UUID | None = None) -> KnowledgeBase:
    return KnowledgeBase(
        id=kb_id or uuid4(),
        tenant_id=uuid4(),
        name="MyKB",
        description=None,
        chunking_config=ChunkingConfig(strategy="fixed", chunk_size=300, chunk_overlap=50),
        embedding_selection=EmbeddingSelection(
            credential_id=uuid4(),
            model_id="bge-m3",
            dim=1024,
        ),
        created_at=_NOW,
        updated_at=_NOW,
    )


async def test_attach_document_happy_path_saves_and_persists() -> None:
    kb = _kb()
    tenant_id = uuid4()
    storage = _FakeStorage()
    sources = _FakeSourcesRepo()

    result = await attach_document_source(
        kb_repo=_FakeKbRepo(kb),  # type: ignore[arg-type]
        sources_repo=sources,  # type: ignore[arg-type]
        storage=storage,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        kb_id=kb.id,
        filename="doc.pdf",
        mime_type="application/pdf",
        content=b"%PDF-1.4 ...",
    )

    assert isinstance(result, AttachDocumentResult)
    assert result.kb_id == kb.id
    assert result.filename == "doc.pdf"
    assert result.mime_type == "application/pdf"
    assert result.storage_uri.endswith("doc.pdf")

    assert len(storage.saved) == 1
    assert storage.saved[0]["tenant_id"] == tenant_id
    assert storage.saved[0]["content"] == b"%PDF-1.4 ..."

    assert len(sources.inserted) == 1
    inserted = sources.inserted[0]
    assert inserted["kb_id"] == kb.id
    assert inserted["source_id"] == result.source_id
    assert inserted["size_bytes"] == len(b"%PDF-1.4 ...")
    assert inserted["storage_uri"] == result.storage_uri


@pytest.mark.parametrize(
    "mime_type",
    [
        "text/plain",
        "text/csv",
        "text/markdown",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ],
)
async def test_attach_document_accepts_all_supported_mime_types(mime_type: str) -> None:
    kb = _kb()
    result = await attach_document_source(
        kb_repo=_FakeKbRepo(kb),  # type: ignore[arg-type]
        sources_repo=_FakeSourcesRepo(),  # type: ignore[arg-type]
        storage=_FakeStorage(),  # type: ignore[arg-type]
        tenant_id=uuid4(),
        kb_id=kb.id,
        filename="f",
        mime_type=mime_type,
        content=b"x",
    )
    assert result.mime_type == mime_type


async def test_attach_document_unsupported_mime_type_raises_before_touching_ports() -> None:
    kb_repo = _FakeKbRepo(_kb())
    storage = _FakeStorage()
    sources = _FakeSourcesRepo()

    with pytest.raises(ValidationError, match="image/png"):
        await attach_document_source(
            kb_repo=kb_repo,  # type: ignore[arg-type]
            sources_repo=sources,  # type: ignore[arg-type]
            storage=storage,  # type: ignore[arg-type]
            tenant_id=uuid4(),
            kb_id=uuid4(),
            filename="pic.png",
            mime_type="image/png",
            content=b"\x89PNG",
        )

    assert kb_repo.calls == []
    assert storage.saved == []
    assert sources.inserted == []


async def test_attach_document_kb_not_found_wraps_as_knowledge_base_not_found() -> None:
    storage = _FakeStorage()
    sources = _FakeSourcesRepo()

    with pytest.raises(KnowledgeBaseNotFoundError):
        await attach_document_source(
            kb_repo=_FakeKbRepo(None),  # type: ignore[arg-type]
            sources_repo=sources,  # type: ignore[arg-type]
            storage=storage,  # type: ignore[arg-type]
            tenant_id=uuid4(),
            kb_id=uuid4(),
            filename="doc.pdf",
            mime_type="application/pdf",
            content=b"content",
        )

    assert storage.saved == []
    assert sources.inserted == []
