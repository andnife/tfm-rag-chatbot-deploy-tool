"""End-to-end ingestion of DOCX, CSV, and Markdown documents.

Mirrors `test_doc_ingestion_flow.py` but parameterised over the three
new loaders shipped in CAP-18.
"""
import asyncio
import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from qdrant_client import AsyncQdrantClient
from sqlalchemy import text

import tfm_rag.infrastructure.api.dependencies as _deps
from tfm_rag.infrastructure.api.app import app
from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings, get_settings

FIXTURES = Path(__file__).parent.parent / "fixtures" / "loaders"


@pytest.fixture
async def _clean_state(settings: Settings) -> None:
    # Ensure the storage directory exists so the app can write uploaded files.
    storage_path = os.environ.get("STORAGE_LOCAL_PATH", "/tmp/tfm_rag_storage")
    Path(storage_path).mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - test fixture setup
    # Clear the lru_cache so the app picks up any env overrides set by monkeypatch.
    get_settings.cache_clear()

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
    _deps._session_factory = None


@pytest.mark.integration
@pytest.mark.parametrize(
    "filename,mime_type",
    [
        ("sample.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("sample.csv", "text/csv"),
        ("sample.md", "text/markdown"),
    ],
)
async def test_oe2_loader_ingests_to_done_with_chunks(
    _clean_state: None,
    settings: Settings,
    filename: str,
    mime_type: str,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        reg = await client.post(
            "/api/auth/register",
            json={"email": f"oe2-{filename}@example.com", "password": "correctpassword"},
        )
        assert reg.status_code == 201, reg.text
        token = reg.json()["access_token"]
        tenant_id = reg.json()["tenant_id"]
        h = {"Authorization": f"Bearer {token}"}

        creds = (await client.get("/api/credentials", headers=h)).json()
        cred_id = next(c for c in creds if c["provider_id"] == "ollama")["id"]

        create_kb = await client.post(
            "/api/knowledge-bases",
            headers=h,
            json={
                "name": f"OE2-{filename}",
                "embedding_selection": {
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

        body = (FIXTURES / filename).read_bytes()
        upload = await client.post(
            f"/api/knowledge-bases/{kb_id}/sources/documents",
            headers=h,
            files={"file": (filename, body, mime_type)},
        )
        assert upload.status_code == 201, upload.text
        job_id = upload.json()["job_id"]
        source_id = upload.json()["source_id"]

        last_status = None
        last_body = None
        for _ in range(60):
            await asyncio.sleep(1)
            poll = await client.get(f"/api/ingestion-jobs/{job_id}", headers=h)
            assert poll.status_code == 200, poll.text
            last_body = poll.json()
            last_status = last_body["status"]
            if last_status in {"done", "failed"}:
                break
        assert last_status == "done", (
            f"Expected done for {filename}, got {last_status}: {last_body!r}"
        )

        kb_detail = await client.get(f"/api/knowledge-bases/{kb_id}", headers=h)
        sources = kb_detail.json()["sources"]
        assert any(
            s["id"] == source_id and s["ingest_status"] == "done" for s in sources
        ), f"Source for {filename} not in done state"

        qclient = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
        try:
            collection = f"kb_chunks__{tenant_id}__1024"
            count = await qclient.count(collection_name=collection, count_filter=None, exact=True)
            assert count.count > 0, f"No Qdrant points for {filename}"
        finally:
            await qclient.close()
