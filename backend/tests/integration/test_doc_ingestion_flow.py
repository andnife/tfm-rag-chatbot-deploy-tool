import asyncio

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
from tfm_rag.infrastructure.settings import Settings


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
    # a fresh event loop binding.
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
        token = reg.json()["access_token"]
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
                    "credential_id": cred_id,
                    "model_id": "bge-m3",
                    "dim": 1024,
                },
                # Opt in to per-document descriptions (C1) — since the refactor
                # this is a first-class ModelRef on the KB, not an implicit
                # provider default. Small local model keeps the test fast.
                "description_llm": {
                    "credential_id": cred_id,
                    "model_id": "gemma3:1b",
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

        # C1: an auto-generated description was persisted for the document.
        engine = build_engine(settings.postgres_url)
        try:
            async with engine.connect() as conn:
                desc = (await conn.execute(
                    text("SELECT description FROM sources WHERE id = :sid"),
                    {"sid": source_id},
                )).scalar_one()
        finally:
            await engine.dispose()
        assert desc is not None and desc.strip(), (
            "Expected a non-empty sources.description after ingestion (C1)"
        )
