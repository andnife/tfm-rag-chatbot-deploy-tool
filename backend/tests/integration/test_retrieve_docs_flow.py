import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
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
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    async with factory() as s:
        await s.execute(text(
            "TRUNCATE chatbot_knowledge_base, chatbots, ingestion_jobs, "
            "sources, knowledge_bases, provider_credentials, users, tenants "
            "RESTART IDENTITY CASCADE"
        ))
        await s.commit()
    await engine.dispose()
    _deps._session_factory = None


async def _register(client: AsyncClient, email: str) -> tuple[str, str]:
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "correctpassword"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return body["token"], body["tenant_id"]


@pytest.mark.integration
async def test_search_returns_matching_chunk(_clean_state: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, _ = await _register(client, "search-user@example.com")
        h = {"Authorization": f"Bearer {token}"}

        creds = (await client.get("/api/credentials", headers=h)).json()
        cred_id = next(c for c in creds if c["provider_id"] == "ollama")["id"]

        r = await client.post(
            "/api/knowledge-bases", headers=h,
            json={
                "name": "SearchKB",
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
        assert r.status_code == 201, r.text
        kb_id = r.json()["id"]

        # Body designed so one chunk is "about pineapples" and another is
        # "about typewriters"; a query for "pineapples" should outrank the
        # typewriter chunk.
        body = (
            b"Pineapples are tropical fruit that grow on a low plant. "
            b"They are sweet and acidic. Many people enjoy pineapple slices "
            b"with ham on pizza, which is famously controversial.\n\n"
            b"Typewriters are mechanical writing machines that became popular "
            b"in offices in the late 19th and early 20th centuries. They use "
            b"a ribbon of inked fabric to imprint letters onto paper."
        )
        upload = await client.post(
            f"/api/knowledge-bases/{kb_id}/sources/documents",
            headers=h,
            files={"file": ("manual.txt", body, "text/plain")},
        )
        assert upload.status_code == 201, upload.text
        job_id = upload.json()["job_id"]

        # Wait for ingestion to finish
        last = None
        for _ in range(60):
            await asyncio.sleep(1)
            r = await client.get(f"/api/ingestion-jobs/{job_id}", headers=h)
            assert r.status_code == 200
            last = r.json()
            if last["status"] in {"done", "failed"}:
                break
        assert last["status"] == "done", f"ingestion did not finish: {last}"

        # Search
        r = await client.post(
            f"/api/knowledge-bases/{kb_id}/search", headers=h,
            json={"query": "tropical fruit", "top_k": 3},
        )
        assert r.status_code == 200, r.text
        hits = r.json()
        assert len(hits) >= 1
        assert all("score" in h for h in hits)
        # The top hit should mention pineapples, not typewriters
        top = hits[0]
        assert "pineapple" in top["content"].lower(), top
        assert top["source_filename"] == "manual.txt"


@pytest.mark.integration
async def test_search_returns_empty_for_empty_query(_clean_state: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, _ = await _register(client, "empty-query@example.com")
        h = {"Authorization": f"Bearer {token}"}

        creds = (await client.get("/api/credentials", headers=h)).json()
        cred_id = next(c for c in creds if c["provider_id"] == "ollama")["id"]

        r = await client.post(
            "/api/knowledge-bases", headers=h,
            json={
                "name": "EmptyQ",
                "embedding_selection": {
                    "provider_id": "ollama",
                    "credential_id": cred_id,
                    "model_id": "bge-m3",
                    "dim": 1024,
                },
            },
        )
        kb_id = r.json()["id"]

        r = await client.post(
            f"/api/knowledge-bases/{kb_id}/search", headers=h,
            json={"query": "   "},
        )
        assert r.status_code == 200
        assert r.json() == []


@pytest.mark.integration
async def test_search_on_other_tenants_kb_returns_404(_clean_state: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        alice_token, _ = await _register(client, "alice-search@example.com")
        bob_token, _ = await _register(client, "bob-search@example.com")

        creds = (await client.get(
            "/api/credentials",
            headers={"Authorization": f"Bearer {alice_token}"},
        )).json()
        alice_cred = next(c for c in creds if c["provider_id"] == "ollama")["id"]

        r = await client.post(
            "/api/knowledge-bases",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={
                "name": "AlicePrivate",
                "embedding_selection": {
                    "provider_id": "ollama",
                    "credential_id": alice_cred,
                    "model_id": "bge-m3",
                    "dim": 1024,
                },
            },
        )
        kb_id = r.json()["id"]

        # Bob tries to search Alice's KB
        r = await client.post(
            f"/api/knowledge-bases/{kb_id}/search",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={"query": "anything"},
        )
        assert r.status_code == 404
