# CAP-KB-DOC-SOURCES Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Ship the M2 demo end-to-end — an authenticated user creates a KB with Ollama embedding, uploads a PDF (or TXT) via the API, sees an `IngestionJob` row that progresses from `queued → running → done`, and ends up with one Qdrant point per chunk. After this plan, plan #12 (CAP-CHAT-DOC-RETRIEVAL) can search those points.

**Architecture:**
- Three new use cases: `AttachDocumentSource` (persist file + Source row, no Qdrant), `IngestSource` (background pipeline: storage → loader → chunker → embedder → Qdrant upsert), `ReindexSource` (delete chunks for source, then ingest again — idempotent).
- Four new domain ports (`Storage`, `DocumentLoader`, `Chunker`, `Embedder`) with one adapter each in this plan: `LocalStorage`, `PdfLoader` + `TxtLoader` (dispatch by mime_type), `FixedSizeChunker`, `OllamaEmbedder`.
- New `ingestion_jobs` table (deferred in plan #4); ORM row + repo. Migration 0005 adds it. Background execution piggybacks on `JobsRunner` from plan #4, but the actual job creates its own DB session (the request session is closed once the HTTP response is sent).
- `QdrantStore` gains two methods: `upsert_points(collection, points)` and `delete_by_source(collection, tenant_id, source_id)`. The collection is the one that `CreateKnowledgeBase` provisioned in plan #7.

**Tech Stack:** `pypdf>=5.1` (new dep, pure-Python MIT) for PDF text extraction. Everything else is reused.

**Depends on:** plan #4 (JobsRunner + IngestionJob entity), plan #5 (BootstrapTenant), plan #6 (catalog + credentials), plan #7 (KB CRUD + Source row + Qdrant collection per `(tenant, dim)`).

**Out of scope (deferred):**
- Cloud `DocumentSource` (gdrive/s3) → later plan (e.g. #8b in a future milestone). The document tester in `SOURCE_CONNECTION_TESTERS["document"]` stays unregistered; upload has nothing to test.
- File loaders for `docx`, `csv`, `md`, `xlsx` → trivial horizontal expansion once PDF + TXT prove the pipeline.
- `openai_compat` embedder adapter → later. Ollama is the M2 default per spec roadmap; the catalog already advertises both.
- Chunking strategies other than `fixed`: `recursive` and `by_paragraph` ChunkingConfig values are still accepted by `ChunkingConfig.__post_init__` (plan #7) but `FixedSizeChunker` ignores `strategy`. The Chunker port lets a future plan swap implementations without touching use cases.

---

## File structure

```
backend/src/tfm_rag/
├── domain/
│   ├── ports/
│   │   ├── storage.py                # Storage protocol
│   │   ├── document_loader.py        # DocumentLoader protocol
│   │   ├── chunker.py                # Chunker protocol + Chunk dataclass
│   │   └── embedder.py               # Embedder protocol
│   └── errors/
│       └── knowledge.py              # +UnsupportedDocumentTypeError already in plan #7; add IngestionFailedError, IngestionJobNotFoundError
├── infrastructure/
│   ├── persistence/
│   │   ├── models/ingestion_jobs.py
│   │   └── repositories/ingestion_jobs_repo.py
│   ├── storage/
│   │   ├── __init__.py
│   │   └── local.py                  # LocalStorage adapter
│   ├── document_loaders/
│   │   ├── __init__.py
│   │   ├── dispatcher.py             # by-mime-type dispatch
│   │   ├── pdf.py                    # PdfLoader (pypdf)
│   │   └── txt.py                    # TxtLoader
│   ├── chunkers/
│   │   ├── __init__.py
│   │   └── fixed_size.py             # FixedSizeChunker
│   ├── embedders/
│   │   ├── __init__.py
│   │   └── ollama.py                 # OllamaEmbedder
│   └── vector_store/
│       └── qdrant_client.py          # MODIFY: add upsert_points + delete_by_source
└── application/
    └── knowledge/
        ├── attach_document_source.py
        ├── ingest_source.py
        ├── reindex_source.py
        └── get_ingestion_job.py

backend/alembic/env.py                # MODIFY: register ingestion_jobs model
backend/alembic/versions/
└── 0005_ingestion_jobs.py

backend/src/tfm_rag/infrastructure/api/routers/
├── knowledge_bases.py                # MODIFY: add POST /sources/documents + POST /sources/{id}/reindex
└── ingestion_jobs.py                 # NEW: GET /api/ingestion-jobs/{id}

backend/pyproject.toml                # MODIFY: add pypdf>=5.1

backend/tests/unit/
├── test_fixed_size_chunker.py
├── test_pdf_loader.py
├── test_txt_loader.py
├── test_loader_dispatcher.py
├── test_local_storage.py
└── test_ingest_pipeline.py           # IngestSource pipeline with fakes

backend/tests/integration/
└── test_doc_ingestion_flow.py        # upload TXT → poll job → verify Qdrant points
```

---

## Task 1 — Add pypdf + domain ports

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/src/tfm_rag/domain/ports/storage.py`
- Create: `backend/src/tfm_rag/domain/ports/document_loader.py`
- Create: `backend/src/tfm_rag/domain/ports/chunker.py`
- Create: `backend/src/tfm_rag/domain/ports/embedder.py`
- Modify: `backend/src/tfm_rag/domain/errors/knowledge.py` (add `IngestionFailedError`, `IngestionJobNotFoundError`)

- [ ] **Step 1.1: Add pypdf to dependencies**

Edit `backend/pyproject.toml` — inside the `[project] dependencies` list, append `"pypdf>=5.1",` (keep the existing entries; insert after `"qdrant-client>=1.12",`). Then:

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
pip install pypdf
python -c "import pypdf; print(pypdf.__version__)"
```

Expected: prints a 5.x version (e.g. `5.1.0`). No errors.

- [ ] **Step 1.2: Create `backend/src/tfm_rag/domain/ports/storage.py`**

```python
from typing import Protocol
from uuid import UUID


class Storage(Protocol):
    """Where uploaded document bytes live before ingestion.

    Implementations return an opaque `storage_uri` from `save`; pass it back
    to `load` to retrieve the same bytes. Plan #8 ships a local-filesystem
    adapter; a future plan can swap in S3 without touching use cases.
    """

    async def save(
        self,
        *,
        tenant_id: UUID,
        source_id: UUID,
        filename: str,
        content: bytes,
    ) -> str: ...

    async def load(self, storage_uri: str) -> bytes: ...

    async def delete(self, storage_uri: str) -> None: ...
```

- [ ] **Step 1.3: Create `backend/src/tfm_rag/domain/ports/document_loader.py`**

```python
from typing import Protocol


class DocumentLoader(Protocol):
    """Extracts plain text from a single document of one mime type."""

    mime_type: str

    async def load(self, content: bytes) -> str: ...
```

- [ ] **Step 1.4: Create `backend/src/tfm_rag/domain/ports/chunker.py`**

```python
from dataclasses import dataclass
from typing import Any, Protocol

from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig


@dataclass(frozen=True, slots=True)
class Chunk:
    """One unit of text that will become one Qdrant point.

    `metadata` is forwarded verbatim into the Qdrant point payload alongside
    `tenant_id`, `kb_id`, `source_id`, `chunk_index`, `content`.
    """

    index: int
    text: str
    metadata: dict[str, Any]


class Chunker(Protocol):
    def chunk(self, text: str, config: ChunkingConfig) -> list[Chunk]: ...
```

- [ ] **Step 1.5: Create `backend/src/tfm_rag/domain/ports/embedder.py`**

```python
from typing import Protocol


class Embedder(Protocol):
    """Turns texts into vectors. One model per call.

    `base_url` is the provider endpoint; for SERVER_ENV providers (Ollama)
    use cases inject the value from Settings. For TENANT_CREDENTIAL
    providers, the caller decrypts the credential and supplies it.
    """

    async def embed(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model_id: str,
        texts: list[str],
    ) -> list[list[float]]: ...
```

- [ ] **Step 1.6: Extend `backend/src/tfm_rag/domain/errors/knowledge.py`**

Append these two error classes to the existing module (do not remove anything already there):

```python


class IngestionFailedError(DomainError):
    """Raised when the ingestion pipeline fails for a single source."""


class IngestionJobNotFoundError(NotFoundError):
    """Raised when an IngestionJob row does not exist in the tenant."""
```

- [ ] **Step 1.7: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/pyproject.toml backend/src/tfm_rag/domain/ports/storage.py backend/src/tfm_rag/domain/ports/document_loader.py backend/src/tfm_rag/domain/ports/chunker.py backend/src/tfm_rag/domain/ports/embedder.py backend/src/tfm_rag/domain/errors/knowledge.py
git commit -m "feat(domain): Storage/Loader/Chunker/Embedder ports + ingestion errors + pypdf dep"
```

---

## Task 2 — Persistence: ingestion_jobs ORM + migration 0005 + repo

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/persistence/models/ingestion_jobs.py`
- Create: `backend/alembic/versions/0005_ingestion_jobs.py`
- Modify: `backend/alembic/env.py` (register the new module)
- Create: `backend/src/tfm_rag/infrastructure/persistence/repositories/ingestion_jobs_repo.py`
- Create: `backend/tests/integration/test_ingestion_jobs_migration.py`

- [ ] **Step 2.1: Write the failing integration test**

Create `backend/tests/integration/test_ingestion_jobs_migration.py`:

```python
import asyncio
import subprocess

import pytest
from sqlalchemy import inspect

from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings


@pytest.mark.integration
async def test_migration_0005_creates_ingestion_jobs(settings: Settings) -> None:
    result = await asyncio.to_thread(
        subprocess.run,
        ["alembic", "upgrade", "head"],
        cwd=".",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    engine = build_engine(settings.postgres_url)
    build_session_factory(engine)
    async with engine.connect() as conn:
        tables = await conn.run_sync(
            lambda sc: inspect(sc).get_table_names()
        )
        assert "ingestion_jobs" in tables
        cols = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("ingestion_jobs")}
        )
        assert {
            "id", "source_id", "tenant_id", "status",
            "progress", "error", "started_at", "finished_at",
        } <= cols
    await engine.dispose()
```

- [ ] **Step 2.2: Create `backend/src/tfm_rag/infrastructure/persistence/models/ingestion_jobs.py`**

```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from tfm_rag.infrastructure.persistence.base import Base


class IngestionJobRow(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','done','failed')",
            name="ck_ingestion_jobs_status",
        ),
        CheckConstraint(
            "progress BETWEEN 0 AND 100",
            name="ck_ingestion_jobs_progress",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

- [ ] **Step 2.3: Create `backend/alembic/versions/0005_ingestion_jobs.py`**

```python
"""create ingestion_jobs table

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-21 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "progress", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "finished_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','done','failed')",
            name="ck_ingestion_jobs_status",
        ),
        sa.CheckConstraint(
            "progress BETWEEN 0 AND 100",
            name="ck_ingestion_jobs_progress",
        ),
    )
    op.create_index(
        "ix_ingestion_jobs_source_id", "ingestion_jobs", ["source_id"]
    )
    op.create_index(
        "ix_ingestion_jobs_tenant_id", "ingestion_jobs", ["tenant_id"]
    )
    op.create_index(
        "ix_ingestion_jobs_status", "ingestion_jobs", ["status"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ingestion_jobs_status", table_name="ingestion_jobs"
    )
    op.drop_index(
        "ix_ingestion_jobs_tenant_id", table_name="ingestion_jobs"
    )
    op.drop_index(
        "ix_ingestion_jobs_source_id", table_name="ingestion_jobs"
    )
    op.drop_table("ingestion_jobs")
```

- [ ] **Step 2.4: Register the new model in `backend/alembic/env.py`**

Insert `ingestion_jobs` into the existing `from tfm_rag.infrastructure.persistence.models import (...)` block so Base.metadata sees it. The block should end up like:

```python
from tfm_rag.infrastructure.persistence.models import (
    ingestion_jobs,  # noqa: F401
    knowledge_bases,  # noqa: F401
    provider_credentials,  # noqa: F401
    sources,  # noqa: F401
    tenants,  # noqa: F401
    users,  # noqa: F401
)
```

- [ ] **Step 2.5: Create `backend/src/tfm_rag/infrastructure/persistence/repositories/ingestion_jobs_repo.py`**

```python
from sqlalchemy import select

from tfm_rag.infrastructure.persistence.models.ingestion_jobs import (
    IngestionJobRow,
)
from tfm_rag.infrastructure.persistence.repository import BaseRepository


class IngestionJobRepository(BaseRepository[IngestionJobRow]):
    model = IngestionJobRow

    async def list_for_source(self, source_id: str) -> list[IngestionJobRow]:
        stmt = (
            select(IngestionJobRow)
            .where(
                IngestionJobRow.tenant_id == self._ctx.tenant_id,
                IngestionJobRow.source_id == source_id,
            )
            .order_by(IngestionJobRow.started_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())
```

- [ ] **Step 2.6: Reset DB and run the migration test**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
docker exec tfm-rag-postgres-1 psql -U tfm -d tfm_rag \
  -c "DROP TABLE IF EXISTS ingestion_jobs, sources, knowledge_bases, provider_credentials, users, tenants, alembic_version CASCADE;"
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
pytest tests/integration/test_ingestion_jobs_migration.py -m integration -v
```

Expected: PASS.

- [ ] **Step 2.7: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/infrastructure/persistence/models/ingestion_jobs.py backend/alembic/versions/0005_ingestion_jobs.py backend/alembic/env.py backend/src/tfm_rag/infrastructure/persistence/repositories/ingestion_jobs_repo.py backend/tests/integration/test_ingestion_jobs_migration.py
git commit -m "feat(infra): ingestion_jobs ORM + migration 0005 + repo"
```

---

## Task 3 — Adapters: storage, loaders, chunker, embedder, Qdrant extensions

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/storage/__init__.py` (empty)
- Create: `backend/src/tfm_rag/infrastructure/storage/local.py`
- Create: `backend/src/tfm_rag/infrastructure/document_loaders/__init__.py` (empty)
- Create: `backend/src/tfm_rag/infrastructure/document_loaders/pdf.py`
- Create: `backend/src/tfm_rag/infrastructure/document_loaders/txt.py`
- Create: `backend/src/tfm_rag/infrastructure/document_loaders/dispatcher.py`
- Create: `backend/src/tfm_rag/infrastructure/chunkers/__init__.py` (empty)
- Create: `backend/src/tfm_rag/infrastructure/chunkers/fixed_size.py`
- Create: `backend/src/tfm_rag/infrastructure/embedders/__init__.py` (empty)
- Create: `backend/src/tfm_rag/infrastructure/embedders/ollama.py`
- Modify: `backend/src/tfm_rag/infrastructure/vector_store/qdrant_client.py` (add `upsert_points`, `delete_by_source`)
- Create: 5 unit test files in `backend/tests/unit/`

- [ ] **Step 3.1: Write the failing unit tests for the chunker**

Create `backend/tests/unit/test_fixed_size_chunker.py`:

```python
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.infrastructure.chunkers.fixed_size import FixedSizeChunker


def test_chunks_short_text_into_single_chunk() -> None:
    chunker = FixedSizeChunker()
    chunks = chunker.chunk(
        "Hello world.",
        ChunkingConfig(strategy="fixed", chunk_size=1000, chunk_overlap=200),
    )
    assert len(chunks) == 1
    assert chunks[0].text == "Hello world."
    assert chunks[0].index == 0


def test_chunks_long_text_with_overlap() -> None:
    chunker = FixedSizeChunker()
    text = "abcdefghij" * 50  # 500 chars
    chunks = chunker.chunk(
        text,
        ChunkingConfig(strategy="fixed", chunk_size=200, chunk_overlap=50),
    )
    # 500 chars, chunk_size=200, stride=150 → chunks at 0, 150, 300, ... up to len(text)
    assert len(chunks) >= 3
    assert chunks[0].text == text[0:200]
    assert chunks[1].text == text[150:350]
    assert all(c.index == i for i, c in enumerate(chunks))


def test_empty_text_yields_no_chunks() -> None:
    chunker = FixedSizeChunker()
    chunks = chunker.chunk(
        "",
        ChunkingConfig(strategy="fixed", chunk_size=200, chunk_overlap=50),
    )
    assert chunks == []


def test_whitespace_only_text_yields_no_chunks() -> None:
    chunker = FixedSizeChunker()
    chunks = chunker.chunk(
        "   \n\n\t  ",
        ChunkingConfig(strategy="fixed", chunk_size=200, chunk_overlap=50),
    )
    assert chunks == []
```

- [ ] **Step 3.2: Create `backend/src/tfm_rag/infrastructure/chunkers/fixed_size.py`**

```python
from tfm_rag.domain.ports.chunker import Chunk
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig


class FixedSizeChunker:
    """Naive fixed-width chunker — slides a window of `chunk_size` characters
    with a stride of `chunk_size - chunk_overlap`.

    `ChunkingConfig.strategy` is ignored: plan #8 ships one implementation.
    A later plan can introduce per-strategy chunkers behind the same port.
    """

    def chunk(self, text: str, config: ChunkingConfig) -> list[Chunk]:
        text = text.strip()
        if not text:
            return []
        size = config.chunk_size
        stride = size - config.chunk_overlap
        chunks: list[Chunk] = []
        i = 0
        index = 0
        n = len(text)
        while i < n:
            chunks.append(
                Chunk(
                    index=index,
                    text=text[i : i + size],
                    metadata={"chunk_start": i, "chunk_end": min(i + size, n)},
                )
            )
            index += 1
            i += stride
            if i + size >= n and i + stride < n:
                # Final partial window
                chunks.append(
                    Chunk(
                        index=index,
                        text=text[i:n],
                        metadata={"chunk_start": i, "chunk_end": n},
                    )
                )
                break
        return chunks
```

- [ ] **Step 3.3: Write the failing test for the TXT loader**

Create `backend/tests/unit/test_txt_loader.py`:

```python
import pytest

from tfm_rag.infrastructure.document_loaders.txt import TxtLoader


@pytest.mark.asyncio
async def test_txt_loader_decodes_utf8() -> None:
    loader = TxtLoader()
    text = await loader.load("hola, mundo — ÿ".encode("utf-8"))
    assert text == "hola, mundo — ÿ"


@pytest.mark.asyncio
async def test_txt_loader_handles_crlf() -> None:
    loader = TxtLoader()
    text = await loader.load(b"line1\r\nline2\r\n")
    assert "line1" in text
    assert "line2" in text


@pytest.mark.asyncio
async def test_txt_loader_falls_back_to_latin1_on_bad_utf8() -> None:
    loader = TxtLoader()
    # Pure latin-1 bytes that would raise as utf-8
    text = await loader.load(b"caf\xe9")
    assert "café" in text
```

- [ ] **Step 3.4: Create `backend/src/tfm_rag/infrastructure/document_loaders/txt.py`**

```python
class TxtLoader:
    mime_type = "text/plain"

    async def load(self, content: bytes) -> str:
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return content.decode("latin-1")
```

- [ ] **Step 3.5: Write the failing test for the PDF loader**

Create `backend/tests/unit/test_pdf_loader.py`:

```python
from io import BytesIO

import pytest
from pypdf import PdfWriter

from tfm_rag.infrastructure.document_loaders.pdf import PdfLoader


def _make_one_page_pdf(text: str) -> bytes:
    """Build a minimal PDF in memory whose first page contains `text`.

    `pypdf.PdfWriter.add_blank_page` + an explicit text stream avoids
    pulling in reportlab as a test dep.
    """
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    page.merge_page(page)  # noop; ensures Resources dict exists
    # We embed the text via the internal /Contents stream so pypdf can
    # extract it on the way out.
    from pypdf.generic import ContentStream, DecodedStreamObject, NameObject

    content_str = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    stream = DecodedStreamObject()
    stream.set_data(content_str)
    page[NameObject("/Contents")] = stream
    # Provide a default Type1 font so the text op decodes:
    from pypdf.generic import DictionaryObject

    font = DictionaryObject()
    font[NameObject("/Type")] = NameObject("/Font")
    font[NameObject("/Subtype")] = NameObject("/Type1")
    font[NameObject("/BaseFont")] = NameObject("/Helvetica")
    resources = page.get("/Resources")
    if not isinstance(resources, DictionaryObject):
        resources = DictionaryObject()
        page[NameObject("/Resources")] = resources
    fonts = DictionaryObject()
    fonts[NameObject("/F1")] = font
    resources[NameObject("/Font")] = fonts
    _ = ContentStream  # silence "unused import" when pypdf prunes API
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.mark.asyncio
async def test_pdf_loader_extracts_text() -> None:
    loader = PdfLoader()
    pdf_bytes = _make_one_page_pdf("hello-rag-pipeline")
    text = await loader.load(pdf_bytes)
    assert "hello-rag-pipeline" in text


@pytest.mark.asyncio
async def test_pdf_loader_rejects_non_pdf() -> None:
    loader = PdfLoader()
    with pytest.raises(ValueError, match="PDF"):
        await loader.load(b"not a pdf at all")
```

- [ ] **Step 3.6: Create `backend/src/tfm_rag/infrastructure/document_loaders/pdf.py`**

```python
import asyncio
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class PdfLoader:
    mime_type = "application/pdf"

    async def load(self, content: bytes) -> str:
        def _extract() -> str:
            try:
                reader = PdfReader(BytesIO(content))
            except PdfReadError as exc:
                raise ValueError(f"Not a valid PDF: {exc}") from exc
            parts: list[str] = []
            for page in reader.pages:
                parts.append(page.extract_text() or "")
            return "\n\n".join(p for p in parts if p)

        # pypdf is sync — push it off the event loop.
        return await asyncio.to_thread(_extract)
```

- [ ] **Step 3.7: Write the failing test for the loader dispatcher**

Create `backend/tests/unit/test_loader_dispatcher.py`:

```python
import pytest

from tfm_rag.domain.errors.knowledge import UnsupportedSourceTypeError
from tfm_rag.infrastructure.document_loaders.dispatcher import (
    LoaderDispatcher,
)
from tfm_rag.infrastructure.document_loaders.pdf import PdfLoader
from tfm_rag.infrastructure.document_loaders.txt import TxtLoader


@pytest.mark.asyncio
async def test_dispatcher_picks_pdf_for_application_pdf() -> None:
    d = LoaderDispatcher([PdfLoader(), TxtLoader()])
    loader = d.for_mime("application/pdf")
    assert isinstance(loader, PdfLoader)


@pytest.mark.asyncio
async def test_dispatcher_picks_txt_for_text_plain() -> None:
    d = LoaderDispatcher([PdfLoader(), TxtLoader()])
    loader = d.for_mime("text/plain")
    assert isinstance(loader, TxtLoader)


@pytest.mark.asyncio
async def test_dispatcher_raises_for_unknown_mime() -> None:
    d = LoaderDispatcher([PdfLoader(), TxtLoader()])
    with pytest.raises(UnsupportedSourceTypeError):
        d.for_mime("image/png")
```

- [ ] **Step 3.8: Create `backend/src/tfm_rag/infrastructure/document_loaders/dispatcher.py`**

```python
from collections.abc import Sequence

from tfm_rag.domain.errors.knowledge import UnsupportedSourceTypeError
from tfm_rag.domain.ports.document_loader import DocumentLoader


class LoaderDispatcher:
    """Picks the right loader for an incoming mime_type."""

    def __init__(self, loaders: Sequence[DocumentLoader]) -> None:
        self._by_mime: dict[str, DocumentLoader] = {
            loader.mime_type: loader for loader in loaders
        }

    def for_mime(self, mime_type: str) -> DocumentLoader:
        loader = self._by_mime.get(mime_type)
        if loader is None:
            raise UnsupportedSourceTypeError(
                f"No loader registered for mime_type {mime_type!r}. "
                f"Supported: {sorted(self._by_mime)}"
            )
        return loader
```

- [ ] **Step 3.9: Write the failing test for LocalStorage**

Create `backend/tests/unit/test_local_storage.py`:

```python
from pathlib import Path
from uuid import uuid4

import pytest

from tfm_rag.infrastructure.storage.local import LocalStorage


@pytest.mark.asyncio
async def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path))
    tenant_id = uuid4()
    source_id = uuid4()
    uri = await storage.save(
        tenant_id=tenant_id,
        source_id=source_id,
        filename="hello.txt",
        content=b"hello world",
    )
    assert uri.startswith("file://")
    loaded = await storage.load(uri)
    assert loaded == b"hello world"


@pytest.mark.asyncio
async def test_save_isolates_by_tenant_and_source(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path))
    t1 = uuid4()
    t2 = uuid4()
    s1 = uuid4()
    u1 = await storage.save(
        tenant_id=t1, source_id=s1, filename="a.txt", content=b"one"
    )
    u2 = await storage.save(
        tenant_id=t2, source_id=s1, filename="a.txt", content=b"two"
    )
    assert u1 != u2
    assert await storage.load(u1) == b"one"
    assert await storage.load(u2) == b"two"


@pytest.mark.asyncio
async def test_delete_removes_file(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path))
    uri = await storage.save(
        tenant_id=uuid4(),
        source_id=uuid4(),
        filename="x.txt",
        content=b"x",
    )
    await storage.delete(uri)
    with pytest.raises(FileNotFoundError):
        await storage.load(uri)
```

- [ ] **Step 3.10: Create `backend/src/tfm_rag/infrastructure/storage/local.py`**

```python
import asyncio
from pathlib import Path
from uuid import UUID


class LocalStorage:
    """Filesystem-backed Storage adapter.

    URI scheme: `file://<absolute-path>`. Files live under
    `<root>/tenant_<tenant_id>/<source_id>/<filename>`.
    Filenames are not sanitised beyond rejecting path separators — the
    upstream HTTP layer already validates them.
    """

    def __init__(self, root: str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(
        self, *, tenant_id: UUID, source_id: UUID, filename: str
    ) -> Path:
        if "/" in filename or "\\" in filename or filename in {".", ".."}:
            raise ValueError(f"Invalid filename: {filename!r}")
        return (
            self._root
            / f"tenant_{tenant_id}"
            / str(source_id)
            / filename
        )

    async def save(
        self,
        *,
        tenant_id: UUID,
        source_id: UUID,
        filename: str,
        content: bytes,
    ) -> str:
        path = self._path_for(
            tenant_id=tenant_id, source_id=source_id, filename=filename
        )

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        await asyncio.to_thread(_write)
        return f"file://{path}"

    async def load(self, storage_uri: str) -> bytes:
        path = Path(storage_uri.removeprefix("file://"))
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, storage_uri: str) -> None:
        path = Path(storage_uri.removeprefix("file://"))

        def _delete() -> None:
            if not path.exists():
                return
            path.unlink()
            # Best-effort prune empty parents:
            for parent in (path.parent, path.parent.parent):
                try:
                    parent.rmdir()
                except OSError:
                    break

        await asyncio.to_thread(_delete)
```

- [ ] **Step 3.11: Create `backend/src/tfm_rag/infrastructure/embedders/ollama.py`**

```python
import httpx


class OllamaEmbedder:
    """Calls Ollama's /api/embeddings endpoint, one text at a time.

    Ollama supports batch via /api/embed (newer), but /api/embeddings is the
    older, more stable surface and what the M2 demo runs against.
    """

    async def embed(
        self,
        *,
        base_url: str,
        api_key: str | None,  # noqa: ARG002 — Ollama is keyless
        model_id: str,
        texts: list[str],
    ) -> list[list[float]]:
        results: list[list[float]] = []
        async with httpx.AsyncClient(base_url=base_url, timeout=120.0) as client:
            for t in texts:
                r = await client.post(
                    "/api/embeddings", json={"model": model_id, "prompt": t}
                )
                r.raise_for_status()
                body = r.json()
                vec = body.get("embedding") or []
                if not vec:
                    raise RuntimeError(
                        f"Ollama returned no embedding for model {model_id!r}"
                    )
                results.append(list(vec))
        return results
```

- [ ] **Step 3.12: Extend `backend/src/tfm_rag/infrastructure/vector_store/qdrant_client.py`**

Replace the entire file with:

```python
from typing import Any
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    VectorParams,
)


def collection_name_for(tenant_id: UUID, dim: int) -> str:
    """Derive the Qdrant collection name for a (tenant, dim) pair.

    See spec §9 — one physical collection per (tenant, dim).
    """
    if dim <= 0:
        raise ValueError("dim must be positive")
    return f"kb_chunks__{tenant_id}__{dim}"


class QdrantStore:
    """Thin async wrapper around AsyncQdrantClient with on-demand collections."""

    def __init__(self, url: str, api_key: str | None = None) -> None:
        self._client = AsyncQdrantClient(url=url, api_key=api_key)

    async def ensure_collection(self, tenant_id: UUID, dim: int) -> str:
        name = collection_name_for(tenant_id, dim)
        existing = {c.name for c in (await self._client.get_collections()).collections}
        if name not in existing:
            await self._client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
        return name

    async def upsert_points(
        self,
        *,
        collection: str,
        points: list[tuple[str, list[float], dict[str, Any]]],
    ) -> None:
        """Upsert a list of (point_id, vector, payload) tuples."""
        await self._client.upsert(
            collection_name=collection,
            points=[
                PointStruct(id=pid, vector=vec, payload=payload)
                for pid, vec, payload in points
            ],
        )

    async def delete_by_source(
        self,
        *,
        collection: str,
        tenant_id: UUID,
        source_id: UUID,
    ) -> None:
        """Delete all points whose payload matches both tenant_id and source_id."""
        await self._client.delete(
            collection_name=collection,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="tenant_id",
                            match=MatchValue(value=str(tenant_id)),
                        ),
                        FieldCondition(
                            key="source_id",
                            match=MatchValue(value=str(source_id)),
                        ),
                    ]
                )
            ),
        )

    async def health(self) -> bool:
        try:
            await self._client.get_collections()
            return True
        except Exception:  # noqa: BLE001
            return False

    async def close(self) -> None:
        await self._client.close()
```

- [ ] **Step 3.13: Run the 4 unit tests, confirm all pass**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
pytest tests/unit/test_fixed_size_chunker.py tests/unit/test_txt_loader.py tests/unit/test_pdf_loader.py tests/unit/test_loader_dispatcher.py tests/unit/test_local_storage.py -v
```

Expected: all green. Approximate count: 4 chunker + 3 txt + 2 pdf + 3 dispatcher + 3 storage = **15 PASSED**.

- [ ] **Step 3.14: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/infrastructure/storage backend/src/tfm_rag/infrastructure/document_loaders backend/src/tfm_rag/infrastructure/chunkers backend/src/tfm_rag/infrastructure/embedders backend/src/tfm_rag/infrastructure/vector_store/qdrant_client.py backend/tests/unit/test_fixed_size_chunker.py backend/tests/unit/test_pdf_loader.py backend/tests/unit/test_txt_loader.py backend/tests/unit/test_loader_dispatcher.py backend/tests/unit/test_local_storage.py
git commit -m "feat(infra): adapters for storage, loaders (pdf/txt), chunker, embedder; QdrantStore upsert/delete"
```

---

## Task 4 — Application use cases: AttachDocumentSource + IngestSource + ReindexSource + GetIngestionJob

**Files:**
- Create: `backend/src/tfm_rag/application/knowledge/attach_document_source.py`
- Create: `backend/src/tfm_rag/application/knowledge/ingest_source.py`
- Create: `backend/src/tfm_rag/application/knowledge/reindex_source.py`
- Create: `backend/src/tfm_rag/application/knowledge/get_ingestion_job.py`
- Create: `backend/tests/unit/test_ingest_pipeline.py`

- [ ] **Step 4.1: Write the failing unit tests for the ingestion pipeline**

Create `backend/tests/unit/test_ingest_pipeline.py`:

```python
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from tfm_rag.application.knowledge.ingest_source import (
    IngestionContext,
    run_ingestion_pipeline,
)
from tfm_rag.domain.ports.chunker import Chunk
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection


def _selection(credential_id: UUID | None = None) -> EmbeddingSelection:
    return EmbeddingSelection(
        provider_id="ollama",
        credential_id=credential_id or uuid4(),
        model_id="bge-m3",
        dim=1024,
    )


@pytest.mark.asyncio
async def test_pipeline_loads_chunks_embeds_and_upserts() -> None:
    tenant_id = uuid4()
    kb_id = uuid4()
    source_id = uuid4()
    storage = MagicMock()
    storage.load = AsyncMock(return_value=b"hello world")
    loader = MagicMock()
    loader.load = AsyncMock(return_value="hello world")
    dispatcher = MagicMock()
    dispatcher.for_mime = MagicMock(return_value=loader)
    chunker = MagicMock()
    chunker.chunk = MagicMock(
        return_value=[
            Chunk(index=0, text="hello", metadata={"chunk_start": 0}),
            Chunk(index=1, text="world", metadata={"chunk_start": 6}),
        ]
    )
    embedder = MagicMock()
    embedder.embed = AsyncMock(
        return_value=[[0.1] * 1024, [0.2] * 1024]
    )
    qdrant = MagicMock()
    qdrant.upsert_points = AsyncMock()
    progress_updates: list[int] = []

    async def on_progress(p: int) -> None:
        progress_updates.append(p)

    ctx = IngestionContext(
        tenant_id=tenant_id,
        kb_id=kb_id,
        source_id=source_id,
        storage_uri="file:///tmp/x.txt",
        mime_type="text/plain",
        filename="x.txt",
        chunking_config=ChunkingConfig.default(),
        embedding_selection=_selection(),
        embedder_base_url="http://localhost:11434",
        embedder_api_key=None,
        collection="kb_chunks__t__1024",
    )

    await run_ingestion_pipeline(
        ctx,
        storage=storage,
        loader_dispatcher=dispatcher,
        chunker=chunker,
        embedder=embedder,
        qdrant=qdrant,
        on_progress=on_progress,
    )

    storage.load.assert_awaited_once_with("file:///tmp/x.txt")
    dispatcher.for_mime.assert_called_once_with("text/plain")
    loader.load.assert_awaited_once_with(b"hello world")
    chunker.chunk.assert_called_once()
    embedder.embed.assert_awaited_once()
    qdrant.upsert_points.assert_awaited_once()
    # Verify the upsert payload structure
    call_kwargs = qdrant.upsert_points.await_args.kwargs
    points = call_kwargs["points"]
    assert len(points) == 2
    pid0, vec0, payload0 = points[0]
    assert payload0["tenant_id"] == str(tenant_id)
    assert payload0["kb_id"] == str(kb_id)
    assert payload0["source_id"] == str(source_id)
    assert payload0["chunk_index"] == 0
    assert payload0["content"] == "hello"
    assert len(vec0) == 1024
    # Progress was reported at least at intake (>=0) and completion (100)
    assert 100 in progress_updates


@pytest.mark.asyncio
async def test_pipeline_with_empty_text_makes_no_qdrant_call() -> None:
    storage = MagicMock()
    storage.load = AsyncMock(return_value=b"   ")
    loader = MagicMock()
    loader.load = AsyncMock(return_value="   ")
    dispatcher = MagicMock()
    dispatcher.for_mime = MagicMock(return_value=loader)
    chunker = MagicMock()
    chunker.chunk = MagicMock(return_value=[])
    embedder = MagicMock()
    embedder.embed = AsyncMock(return_value=[])
    qdrant = MagicMock()
    qdrant.upsert_points = AsyncMock()

    ctx = IngestionContext(
        tenant_id=uuid4(),
        kb_id=uuid4(),
        source_id=uuid4(),
        storage_uri="file:///tmp/y.txt",
        mime_type="text/plain",
        filename="y.txt",
        chunking_config=ChunkingConfig.default(),
        embedding_selection=_selection(),
        embedder_base_url="http://localhost:11434",
        embedder_api_key=None,
        collection="kb_chunks__t__1024",
    )

    await run_ingestion_pipeline(
        ctx,
        storage=storage,
        loader_dispatcher=dispatcher,
        chunker=chunker,
        embedder=embedder,
        qdrant=qdrant,
        on_progress=lambda _p: _noop(),
    )

    chunker.chunk.assert_called_once()
    embedder.embed.assert_not_awaited()
    qdrant.upsert_points.assert_not_awaited()


async def _noop() -> None:
    return None
```

- [ ] **Step 4.2: Run the pipeline test, confirm it fails with `ImportError`**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
pytest tests/unit/test_ingest_pipeline.py -v
```

Expected: collection error — `ingest_source` doesn't exist yet.

- [ ] **Step 4.3: Create `backend/src/tfm_rag/application/knowledge/ingest_source.py`**

```python
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid5

from tfm_rag.domain.ports.chunker import Chunker
from tfm_rag.domain.ports.embedder import Embedder
from tfm_rag.domain.ports.storage import Storage
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.infrastructure.document_loaders.dispatcher import LoaderDispatcher
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore

ProgressCallback = Callable[[int], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class IngestionContext:
    tenant_id: UUID
    kb_id: UUID
    source_id: UUID
    storage_uri: str
    mime_type: str
    filename: str
    chunking_config: ChunkingConfig
    embedding_selection: EmbeddingSelection
    embedder_base_url: str
    embedder_api_key: str | None
    collection: str


def _point_id(source_id: UUID, chunk_index: int) -> str:
    """Deterministic UUIDv5 so reindex overwrites the same Qdrant points.

    Uses the source_id itself as the uuid5 namespace; same (source_id,
    chunk_index) always produces the same id.
    """
    return str(uuid5(source_id, f"chunk-{chunk_index}"))


async def run_ingestion_pipeline(
    ctx: IngestionContext,
    *,
    storage: Storage,
    loader_dispatcher: LoaderDispatcher,
    chunker: Chunker,
    embedder: Embedder,
    qdrant: QdrantStore,
    on_progress: ProgressCallback,
) -> None:
    await on_progress(5)

    raw = await storage.load(ctx.storage_uri)
    await on_progress(15)

    loader = loader_dispatcher.for_mime(ctx.mime_type)
    text = await loader.load(raw)
    await on_progress(35)

    chunks = chunker.chunk(text, ctx.chunking_config)
    await on_progress(50)
    if not chunks:
        await on_progress(100)
        return

    vectors = await embedder.embed(
        base_url=ctx.embedder_base_url,
        api_key=ctx.embedder_api_key,
        model_id=ctx.embedding_selection.model_id,
        texts=[c.text for c in chunks],
    )
    await on_progress(85)

    points: list[tuple[str, list[float], dict[str, Any]]] = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        payload: dict[str, Any] = {
            "tenant_id": str(ctx.tenant_id),
            "kb_id": str(ctx.kb_id),
            "source_id": str(ctx.source_id),
            "chunk_index": chunk.index,
            "content": chunk.text,
            "source_filename": ctx.filename,
            **chunk.metadata,
        }
        points.append((_point_id(ctx.source_id, chunk.index), vector, payload))

    await qdrant.upsert_points(collection=ctx.collection, points=points)
    await on_progress(100)
```

Note for the implementer: do NOT change `_point_id` — reindex correctness depends on `(source_id, chunk_index)` producing the same UUID across runs. `uuid5` (deterministic) is the right tool; `uuid4` (random) would break reindex idempotency.

- [ ] **Step 4.4: Run the pipeline tests, confirm they pass**

```bash
pytest tests/unit/test_ingest_pipeline.py -v
```

Expected: 2 PASSED.

- [ ] **Step 4.5: Create `backend/src/tfm_rag/application/knowledge/attach_document_source.py`**

```python
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
```

- [ ] **Step 4.6: Create `backend/src/tfm_rag/application/knowledge/reindex_source.py`**

```python
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.knowledge import (
    KnowledgeBaseNotFoundError,
    SourceNotFoundError,
)
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repositories.sources_repo import (
    SourceRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.vector_store.qdrant_client import (
    QdrantStore,
    collection_name_for,
)

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


async def purge_source_chunks(
    session: AsyncSession,
    ctx: RequestContext,
    qdrant: QdrantStore,
    *,
    kb_repo_factory: KbRepoFactory = _default_kb_repo,
    sources_repo_factory: SrcRepoFactory = _default_src_repo,
    kb_id: UUID,
    source_id: UUID,
) -> None:
    """Idempotent: delete existing Qdrant chunks for `source_id`.

    Used by ReindexSource before re-running the pipeline. Lives here (not in
    `ingest_source.py`) because reindexing is the only caller in plan #8.
    The KB's embedding `dim` selects the collection.
    """
    kb_repo = kb_repo_factory(session, ctx)
    try:
        kb_row = await kb_repo.get(kb_id)
    except Exception as exc:
        raise KnowledgeBaseNotFoundError(str(exc)) from exc
    src_repo = sources_repo_factory(session)
    try:
        await src_repo.get(kb_id, source_id)
    except Exception as exc:
        raise SourceNotFoundError(str(exc)) from exc

    selection = EmbeddingSelection.from_dict(kb_row.embedding_selection)
    collection = collection_name_for(ctx.tenant_id, selection.dim)
    await qdrant.delete_by_source(
        collection=collection,
        tenant_id=ctx.tenant_id,
        source_id=source_id,
    )
```

- [ ] **Step 4.7: Create `backend/src/tfm_rag/application/knowledge/get_ingestion_job.py`**

```python
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import IngestionJobNotFoundError
from tfm_rag.infrastructure.persistence.repositories.ingestion_jobs_repo import (
    IngestionJobRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

RepoFactory = Callable[
    [AsyncSession, RequestContext], IngestionJobRepository
]


def _default_repo(
    session: AsyncSession, ctx: RequestContext
) -> IngestionJobRepository:
    return IngestionJobRepository(session, ctx)


@dataclass(frozen=True, slots=True)
class IngestionJobView:
    id: UUID
    source_id: UUID
    status: str
    progress: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None


async def get_ingestion_job(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    repo_factory: RepoFactory = _default_repo,
    job_id: UUID,
) -> IngestionJobView:
    repo = repo_factory(session, ctx)
    try:
        row = await repo.get(job_id)
    except NotFoundError as exc:
        raise IngestionJobNotFoundError(str(exc)) from exc
    return IngestionJobView(
        id=row.id,
        source_id=row.source_id,
        status=row.status,
        progress=row.progress,
        error=row.error,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )
```

- [ ] **Step 4.8: Run the existing knowledge unit tests to confirm no regression**

```bash
pytest tests/unit/test_knowledge_use_cases.py tests/unit/test_ingest_pipeline.py -v
```

Expected: 12 + 2 = **14 PASSED**.

- [ ] **Step 4.9: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/application/knowledge/attach_document_source.py backend/src/tfm_rag/application/knowledge/ingest_source.py backend/src/tfm_rag/application/knowledge/reindex_source.py backend/src/tfm_rag/application/knowledge/get_ingestion_job.py backend/tests/unit/test_ingest_pipeline.py
git commit -m "feat(knowledge): AttachDocumentSource + IngestSource pipeline + ReindexSource purge + GetIngestionJob"
```

---

## Task 5 — API: upload, reindex, job polling

**Files:**
- Modify: `backend/src/tfm_rag/infrastructure/api/routers/knowledge_bases.py` (add 2 endpoints)
- Create: `backend/src/tfm_rag/infrastructure/api/routers/ingestion_jobs.py`
- Modify: `backend/src/tfm_rag/infrastructure/api/app.py` (mount the new router)

The upload endpoint orchestrates: `attach_document_source` (saves file + Source row + commits the request session) → create `IngestionJob` row → schedule background pipeline. The background coroutine **opens its own session** with the factory because the request session is closed once the response is sent.

- [ ] **Step 5.1: Append the upload + reindex endpoints to `knowledge_bases.py`**

Open `backend/src/tfm_rag/infrastructure/api/routers/knowledge_bases.py`. Add these imports at the top of the file (merge with the existing imports — do not duplicate):

```python
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import BackgroundTasks, File, Form, UploadFile
from sqlalchemy.ext.asyncio import async_sessionmaker

from tfm_rag.application.knowledge.attach_document_source import (
    attach_document_source,
)
from tfm_rag.application.knowledge.ingest_source import (
    IngestionContext,
    run_ingestion_pipeline,
)
from tfm_rag.application.knowledge.reindex_source import purge_source_chunks
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.infrastructure.api.dependencies import _get_factory  # noqa: PLC2701
from tfm_rag.infrastructure.chunkers.fixed_size import FixedSizeChunker
from tfm_rag.infrastructure.document_loaders.dispatcher import LoaderDispatcher
from tfm_rag.infrastructure.document_loaders.pdf import PdfLoader
from tfm_rag.infrastructure.document_loaders.txt import TxtLoader
from tfm_rag.infrastructure.embedders.ollama import OllamaEmbedder
from tfm_rag.infrastructure.jobs.runner import JobsRunner
from tfm_rag.infrastructure.persistence.models.ingestion_jobs import (
    IngestionJobRow,
)
from tfm_rag.infrastructure.persistence.models.knowledge_bases import (
    KnowledgeBaseRow,
)
from tfm_rag.infrastructure.persistence.models.sources import SourceRow
from tfm_rag.infrastructure.storage.local import LocalStorage
from tfm_rag.infrastructure.vector_store.qdrant_client import (
    collection_name_for,
)
from sqlalchemy import select, update
```

Then add the new endpoints and helper at the bottom of the file (before any final blank line):

```python
def _storage(settings: Settings) -> LocalStorage:
    return LocalStorage(root=settings.storage_local_path)


def _loader_dispatcher() -> LoaderDispatcher:
    return LoaderDispatcher([PdfLoader(), TxtLoader()])


async def _ingest_in_background(
    *,
    factory: async_sessionmaker[AsyncSession],
    qdrant_url: str,
    qdrant_api_key: str | None,
    settings: Settings,
    job_id: UUID,
    tenant_id: UUID,
) -> None:
    """Background pipeline. Opens its own session and Qdrant client.

    Updates `ingestion_jobs.status/progress/error/finished_at` as the pipeline
    progresses. Never raises — failures are written to the row.
    """
    qdrant = QdrantStore(url=qdrant_url, api_key=qdrant_api_key)
    try:
        async with factory() as session:
            # Load job + source + KB
            job = (await session.execute(
                select(IngestionJobRow).where(
                    IngestionJobRow.id == job_id,
                    IngestionJobRow.tenant_id == tenant_id,
                )
            )).scalar_one()
            source = (await session.execute(
                select(SourceRow).where(SourceRow.id == job.source_id)
            )).scalar_one()
            kb = (await session.execute(
                select(KnowledgeBaseRow).where(
                    KnowledgeBaseRow.id == source.kb_id,
                    KnowledgeBaseRow.tenant_id == tenant_id,
                )
            )).scalar_one()

            chunking = ChunkingConfig.from_dict(kb.chunking_config)
            selection = EmbeddingSelection.from_dict(kb.embedding_selection)
            collection = collection_name_for(tenant_id, selection.dim)

            payload = source.payload
            ctx = IngestionContext(
                tenant_id=tenant_id,
                kb_id=kb.id,
                source_id=source.id,
                storage_uri=payload["storage_uri"],
                mime_type=payload["mime_type"],
                filename=payload["filename"],
                chunking_config=chunking,
                embedding_selection=selection,
                embedder_base_url=settings.ollama_base_url,
                embedder_api_key=None,  # Ollama is keyless in M2
                collection=collection,
            )

            # Mark as running
            job.status = "running"
            job.progress = 0
            source.ingest_status = "running"
            await session.commit()

            async def _on_progress(p: int) -> None:
                async with factory() as s2:
                    await s2.execute(
                        update(IngestionJobRow)
                        .where(IngestionJobRow.id == job_id)
                        .values(progress=p)
                    )
                    await s2.commit()

            try:
                await run_ingestion_pipeline(
                    ctx,
                    storage=_storage(settings),
                    loader_dispatcher=_loader_dispatcher(),
                    chunker=FixedSizeChunker(),
                    embedder=OllamaEmbedder(),
                    qdrant=qdrant,
                    on_progress=_on_progress,
                )
            except Exception as exc:  # noqa: BLE001
                async with factory() as s3:
                    await s3.execute(
                        update(IngestionJobRow)
                        .where(IngestionJobRow.id == job_id)
                        .values(
                            status="failed",
                            error=str(exc)[:1900],
                            finished_at=datetime.now(timezone.utc),
                        )
                    )
                    await s3.execute(
                        update(SourceRow)
                        .where(SourceRow.id == source.id)
                        .values(
                            ingest_status="failed",
                            error=str(exc)[:1900],
                        )
                    )
                    await s3.commit()
                return

            # Success
            async with factory() as s4:
                now = datetime.now(timezone.utc)
                await s4.execute(
                    update(IngestionJobRow)
                    .where(IngestionJobRow.id == job_id)
                    .values(
                        status="done",
                        progress=100,
                        finished_at=now,
                    )
                )
                await s4.execute(
                    update(SourceRow)
                    .where(SourceRow.id == source.id)
                    .values(
                        ingest_status="done",
                        last_ingest_at=now,
                        error=None,
                    )
                )
                await s4.commit()
    finally:
        await qdrant.close()


class UploadDocOut(BaseModel):
    source_id: str
    job_id: str


@router.post(
    "/{kb_id}/sources/documents",
    status_code=201,
    response_model=UploadDocOut,
)
async def upload_document_(
    kb_id: UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),  # noqa: B008
    filename: str | None = Form(default=None),
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> UploadDocOut:
    content = await file.read()
    name = filename or file.filename or "document"
    mime = file.content_type or "application/octet-stream"
    try:
        result = await attach_document_source(
            session,
            ctx,
            _storage(settings),
            kb_id=kb_id,
            filename=name,
            mime_type=mime,
            content=content,
        )
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Create the IngestionJob row in the same session (committed by get_session)
    job_id = uuid4()
    session.add(
        IngestionJobRow(
            id=job_id,
            source_id=result.source_id,
            tenant_id=ctx.tenant_id,
            status="queued",
            progress=0,
        )
    )
    await session.flush()

    factory = _get_factory(settings)
    runner = JobsRunner(background_tasks)

    async def _kick() -> None:
        await _ingest_in_background(
            factory=factory,
            qdrant_url=settings.qdrant_url,
            qdrant_api_key=settings.qdrant_api_key,
            settings=settings,
            job_id=job_id,
            tenant_id=ctx.tenant_id,
        )

    runner.schedule(_kick)

    return UploadDocOut(source_id=str(result.source_id), job_id=str(job_id))


@router.post(
    "/{kb_id}/sources/{source_id}/reindex",
    status_code=201,
    response_model=UploadDocOut,
)
async def reindex_source_(
    kb_id: UUID,
    source_id: UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> UploadDocOut:
    qdrant = _qdrant(settings)
    try:
        await purge_source_chunks(
            session, ctx, qdrant,
            kb_id=kb_id, source_id=source_id,
        )
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SourceNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    finally:
        await qdrant.close()

    job_id = uuid4()
    session.add(
        IngestionJobRow(
            id=job_id,
            source_id=source_id,
            tenant_id=ctx.tenant_id,
            status="queued",
            progress=0,
        )
    )
    await session.flush()

    factory = _get_factory(settings)
    runner = JobsRunner(background_tasks)

    async def _kick() -> None:
        await _ingest_in_background(
            factory=factory,
            qdrant_url=settings.qdrant_url,
            qdrant_api_key=settings.qdrant_api_key,
            settings=settings,
            job_id=job_id,
            tenant_id=ctx.tenant_id,
        )

    runner.schedule(_kick)

    return UploadDocOut(source_id=str(source_id), job_id=str(job_id))
```

- [ ] **Step 5.2: Create `backend/src/tfm_rag/infrastructure/api/routers/ingestion_jobs.py`**

```python
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.knowledge.get_ingestion_job import get_ingestion_job
from tfm_rag.domain.errors.knowledge import IngestionJobNotFoundError
from tfm_rag.infrastructure.api.dependencies import (
    get_current_context,
    get_session,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

router = APIRouter(prefix="/api/ingestion-jobs", tags=["ingestion"])


class IngestionJobOut(BaseModel):
    id: str
    source_id: str
    status: str
    progress: int
    error: str | None
    started_at: str
    finished_at: str | None


@router.get("/{job_id}", response_model=IngestionJobOut)
async def get_(
    job_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> IngestionJobOut:
    try:
        view = await get_ingestion_job(session, ctx, job_id=job_id)
    except IngestionJobNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return IngestionJobOut(
        id=str(view.id),
        source_id=str(view.source_id),
        status=view.status,
        progress=view.progress,
        error=view.error,
        started_at=view.started_at.isoformat(),
        finished_at=view.finished_at.isoformat() if view.finished_at else None,
    )
```

- [ ] **Step 5.3: Mount the new router in `backend/src/tfm_rag/infrastructure/api/app.py`**

Update the imports + `include_router` block:

```python
from fastapi import FastAPI

from tfm_rag.infrastructure.api.middleware.tenant_scoping import (
    TenantScopingMiddleware,
)
from tfm_rag.infrastructure.api.routers import (
    auth,
    credentials,
    health,
    ingestion_jobs,
    knowledge_bases,
)
from tfm_rag.infrastructure.settings import get_settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="TFM RAG Chatbot Platform",
        version="0.1.0",
    )
    settings = get_settings()
    app.add_middleware(TenantScopingMiddleware, settings=settings)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(credentials.router)
    app.include_router(knowledge_bases.router)
    app.include_router(ingestion_jobs.router)
    return app


app = create_app()
```

- [ ] **Step 5.4: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/infrastructure/api/routers/knowledge_bases.py backend/src/tfm_rag/infrastructure/api/routers/ingestion_jobs.py backend/src/tfm_rag/infrastructure/api/app.py
git commit -m "feat(api): upload document + reindex + ingestion-jobs polling endpoints"
```

---

## Task 6 — Integration test: end-to-end TXT ingestion

This verifies the M2 demo path against the live stack: register → create KB with Ollama bge-m3 → upload a `.txt` file → poll the ingestion job until done → confirm Qdrant has the expected number of points.

We use a `.txt` (not `.pdf`) for the integration test to keep the test fixture simple and to avoid coupling to `pypdf`'s text-extraction quirks. The PDF path is covered by the unit test (Task 3.5).

**Files:**
- Create: `backend/tests/integration/test_doc_ingestion_flow.py`

- [ ] **Step 6.1: Write the integration test**

Create `backend/tests/integration/test_doc_ingestion_flow.py`:

```python
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from qdrant_client import AsyncQdrantClient
from sqlalchemy import text

from tfm_rag.infrastructure.api.app import app
from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings
import tfm_rag.infrastructure.api.dependencies as _deps


@pytest.fixture
async def _clean_state(settings: Settings) -> None:
    # Reset DB
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    async with factory() as s:
        await s.execute(text(
            "TRUNCATE ingestion_jobs, sources, knowledge_bases, "
            "provider_credentials, users, tenants "
            "RESTART IDENTITY CASCADE"
        ))
        await s.commit()
    await engine.dispose()
    # Reset request-scoped Qdrant + session-factory globals so each test gets
    # a fresh event loop binding (see plan #7 subagent-questions entry).
    _deps._session_factory = None


@pytest.mark.integration
async def test_upload_txt_and_poll_until_done(_clean_state: None, settings: Settings) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register a user
        reg = await client.post(
            "/api/auth/register",
            json={"email": "ingest@example.com", "password": "correctpassword"},
        )
        assert reg.status_code == 201, reg.text
        token = reg.json()["token"]
        h = {"Authorization": f"Bearer {token}"}

        # Find Ollama default credential
        creds = (await client.get("/api/credentials", headers=h)).json()
        cred_id = next(c for c in creds if c["provider_id"] == "ollama")["id"]

        # Create KB
        create_kb = await client.post(
            "/api/knowledge-bases",
            headers=h,
            json={
                "name": "Docs",
                "embedding_selection": {
                    "provider_id": "ollama",
                    "credential_id": cred_id,
                    "model_id": "bge-m3",
                    "dim": 1024,
                },
                "chunking_config": {
                    "strategy": "fixed",
                    "chunk_size": 200,
                    "chunk_overlap": 50,
                },
            },
        )
        assert create_kb.status_code == 201, create_kb.text
        kb_id = create_kb.json()["id"]

        # Upload a .txt with ~5 paragraphs so we get a couple of chunks
        body = ("Lorem ipsum dolor sit amet. " * 30).encode("utf-8")
        upload = await client.post(
            f"/api/knowledge-bases/{kb_id}/sources/documents",
            headers=h,
            files={"file": ("manual.txt", body, "text/plain")},
        )
        assert upload.status_code == 201, upload.text
        job_id = upload.json()["job_id"]
        source_id = upload.json()["source_id"]

        # Poll until done (or fail after ~60s)
        deadline = 60
        last_status = None
        for _ in range(deadline):
            await asyncio.sleep(1)
            poll = await client.get(f"/api/ingestion-jobs/{job_id}", headers=h)
            assert poll.status_code == 200, poll.text
            body_json = poll.json()
            last_status = body_json["status"]
            if last_status in {"done", "failed"}:
                break
        assert last_status == "done", f"Expected done, got {last_status}: {body_json!r}"
        assert body_json["progress"] == 100

        # Verify Source row updated to done
        kb_detail = await client.get(
            f"/api/knowledge-bases/{kb_id}", headers=h
        )
        sources = kb_detail.json()["sources"]
        assert any(
            s["id"] == source_id and s["ingest_status"] == "done"
            for s in sources
        )

        # Verify Qdrant has at least one point with our source_id payload
        qclient = AsyncQdrantClient(
            url=settings.qdrant_url, api_key=settings.qdrant_api_key
        )
        try:
            tenant_id = reg.json()["tenant_id"]
            collection = f"kb_chunks__{tenant_id}__1024"
            count = await qclient.count(
                collection_name=collection,
                count_filter=None,
                exact=True,
            )
            assert count.count >= 1, "Expected at least one Qdrant point after ingestion"
        finally:
            await qclient.close()
```

- [ ] **Step 6.2: Reset stack and run the integration test**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
docker exec tfm-rag-postgres-1 psql -U tfm -d tfm_rag \
  -c "DROP TABLE IF EXISTS ingestion_jobs, sources, knowledge_bases, provider_credentials, users, tenants, alembic_version CASCADE;"
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
alembic upgrade head
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
pytest tests/integration/test_doc_ingestion_flow.py -m integration -v
```

Expected: PASS within ~30s. The Ollama embedder will call out to the local Ollama server, which must have `bge-m3` pulled (it does — pre-seeded by `infra/seed/ollama_pull.sh`).

- [ ] **Step 6.3: Run the full integration suite to confirm no regressions**

```bash
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
pytest tests/integration -m integration -v
```

Expected: **12 PASSED** (the 10 from plan #7 close + Task 2's migration test + Task 6's ingestion test).

- [ ] **Step 6.4: Commit + tag**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/tests/integration/test_doc_ingestion_flow.py
git commit -m "test(knowledge): end-to-end TXT ingestion flow against live Postgres + Qdrant + Ollama"
git tag cap-08-kb-doc-sources
```

---

## What's next (deferred, for handover)

After this plan ships:

- **Plan #9 (CAP-KB-DB-SOURCES)** adds `AttachDatabaseSource` + the SQL drivers (postgres/mysql) + `source_db_credentials` table + the database connection tester registered into `SOURCE_CONNECTION_TESTERS["database"]`.
- **Cloud `DocumentSource`** (gdrive/s3) and additional loaders (docx/csv/md/xlsx) belong to a focused expansion plan once M2 is demoable. The dispatcher in `LoaderDispatcher` was designed to grow horizontally: pass extra loaders into its constructor list.
- **OpenAI-compat embedder** belongs to whichever later plan needs non-Ollama embeddings; the `Embedder` port is provider-agnostic and the credential decryption path already exists in plan #6.
- The `update_knowledge_base` flag `reindex_required` (from plan #7) is still informational only; once we have multiple sources per KB, a follow-up plan can iterate over the KB's DocumentSources and call `ReindexSource` for each. Today's UI presents the flag to the user and they can hit "Reindex" manually per source.
