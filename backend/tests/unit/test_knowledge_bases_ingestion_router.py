"""Wiring tests for the recomposed ingestion endpoints.

`upload_document_` and `reindex_source_` no longer create `IngestionJobRow`
by hand nor call the old `_ingest_in_background`; they now compose repository
ports, create the queued job through `IngestionJobRepository.create_queued_job`,
and schedule `run_ingestion_job` via `_schedule_ingestion`. These tests drive
the endpoints through FastAPI with faked use cases + an in-memory session, so a
stale caller composition surfaces as a failure without a live DB/Qdrant stack.
"""
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tfm_rag.application.knowledge.attach_document_source import (
    AttachDocumentResult,
)
from tfm_rag.infrastructure.api.auth_cookie import COOKIE_NAME
from tfm_rag.infrastructure.api.dependencies import get_session
from tfm_rag.infrastructure.api.middleware.tenant_scoping import (
    TenantScopingMiddleware,
)
from tfm_rag.infrastructure.api.routers import knowledge_bases
from tfm_rag.infrastructure.auth.jwt import encode_jwt
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repositories.sources_repo import (
    SourceRepository,
)
from tfm_rag.infrastructure.settings import Settings, get_settings

SECRET = "x" * 32
FERNET_KEY = "qjd374RRcCpzdVhmmLHCnjxvBfrFwbwErhxIj4nq_XM="


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        postgres_url="postgresql+asyncpg://u:p@h:5432/d",
        qdrant_url="http://qdrant:6333",
        ollama_base_url="http://ollama:11434",
        jwt_secret=SECRET,
        fernet_key=FERNET_KEY,
        cookie_secure=False,
    )


class _FakeSession:
    """Minimal AsyncSession stand-in: records add/flush/commit."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flushed = 0
        self.committed = 0

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.committed += 1


def _build_app(session: _FakeSession) -> FastAPI:
    app = FastAPI()
    settings = _settings()
    app.add_middleware(TenantScopingMiddleware, settings=settings)
    app.include_router(knowledge_bases.router)

    async def _fake_session() -> AsyncIterator[object]:
        yield session

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_settings] = lambda: settings
    return app


def _token(*, tenant_id: Any, user_id: Any) -> str:
    return encode_jwt(
        user_id=user_id, tenant_id=tenant_id, secret=SECRET,
        expires_hours=1, is_superadmin=False,
    )


def test_upload_document_composes_ports_and_schedules_ingestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    kb_id = uuid4()
    source_id = uuid4()
    attach_calls: list[dict[str, Any]] = []
    schedule_calls: list[dict[str, Any]] = []

    async def _fake_attach(
        *,
        kb_repo: Any,
        sources_repo: Any,
        storage: Any,
        tenant_id: Any,
        kb_id: Any,
        filename: str,
        mime_type: str,
        content: bytes,
    ) -> AttachDocumentResult:
        attach_calls.append(
            {
                "kb_repo": kb_repo,
                "sources_repo": sources_repo,
                "tenant_id": tenant_id,
                "kb_id": kb_id,
                "filename": filename,
                "mime_type": mime_type,
                "content": content,
            }
        )
        return AttachDocumentResult(
            source_id=source_id,
            kb_id=kb_id,
            filename=filename,
            mime_type=mime_type,
            storage_uri="file:///x",
        )

    def _fake_schedule(
        *, background_tasks: Any, settings: Any, tenant_id: Any, job_id: Any
    ) -> None:
        schedule_calls.append({"tenant_id": tenant_id, "job_id": job_id})

    monkeypatch.setattr(knowledge_bases, "attach_document_source", _fake_attach)
    monkeypatch.setattr(knowledge_bases, "_schedule_ingestion", _fake_schedule)

    session = _FakeSession()
    client = TestClient(_build_app(session), raise_server_exceptions=True)
    client.cookies.set(COOKIE_NAME, _token(tenant_id=tenant_id, user_id=uuid4()))

    resp = client.post(
        f"/api/knowledge-bases/{kb_id}/sources/documents",
        files={"file": ("doc.txt", b"hello", "text/plain")},
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["source_id"] == str(source_id)
    job_id = body["job_id"]

    # attach was composed with the real repository adapters + tenant_id.
    assert len(attach_calls) == 1
    assert isinstance(attach_calls[0]["kb_repo"], KnowledgeBaseRepository)
    assert isinstance(attach_calls[0]["sources_repo"], SourceRepository)
    assert attach_calls[0]["tenant_id"] == tenant_id
    assert attach_calls[0]["kb_id"] == kb_id

    # The queued job was persisted (via create_queued_job -> session.add) and
    # committed before scheduling; the runner was scheduled with that job_id.
    assert session.committed == 1
    assert len(session.added) == 1  # the IngestionJobRow
    assert len(schedule_calls) == 1
    assert schedule_calls[0]["tenant_id"] == tenant_id
    assert str(schedule_calls[0]["job_id"]) == job_id


def test_reindex_composes_ports_and_schedules_ingestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    kb_id = uuid4()
    source_id = uuid4()
    purge_calls: list[dict[str, Any]] = []
    schedule_calls: list[dict[str, Any]] = []

    async def _fake_purge(
        *,
        kb_repo: Any,
        sources_repo: Any,
        qdrant: Any,
        tenant_id: Any,
        kb_id: Any,
        source_id: Any,
    ) -> None:
        purge_calls.append(
            {
                "kb_repo": kb_repo,
                "sources_repo": sources_repo,
                "tenant_id": tenant_id,
                "kb_id": kb_id,
                "source_id": source_id,
            }
        )

    def _fake_schedule(
        *, background_tasks: Any, settings: Any, tenant_id: Any, job_id: Any
    ) -> None:
        schedule_calls.append({"tenant_id": tenant_id, "job_id": job_id})

    monkeypatch.setattr(knowledge_bases, "purge_source_chunks", _fake_purge)
    monkeypatch.setattr(knowledge_bases, "_schedule_ingestion", _fake_schedule)

    session = _FakeSession()
    client = TestClient(_build_app(session), raise_server_exceptions=True)
    client.cookies.set(COOKIE_NAME, _token(tenant_id=tenant_id, user_id=uuid4()))

    resp = client.post(
        f"/api/knowledge-bases/{kb_id}/sources/{source_id}/reindex",
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["source_id"] == str(source_id)

    assert len(purge_calls) == 1
    assert isinstance(purge_calls[0]["kb_repo"], KnowledgeBaseRepository)
    assert isinstance(purge_calls[0]["sources_repo"], SourceRepository)
    assert purge_calls[0]["tenant_id"] == tenant_id
    assert purge_calls[0]["kb_id"] == kb_id
    assert purge_calls[0]["source_id"] == source_id

    assert session.committed == 1
    assert len(schedule_calls) == 1
    assert str(schedule_calls[0]["job_id"]) == body["job_id"]
