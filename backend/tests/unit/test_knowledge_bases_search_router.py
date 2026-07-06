"""Regression test for `POST /api/knowledge-bases/{kb_id}/search`.

Task 6 resignatured `retrieve_docs` to a fully keyword-only signature
(`tenant_id, qdrant, dispatcher, kb_repo, credentials_repo, encryptor,
ollama_base_url, kb_ids, ...`), but the `/search` handler in
`routers/knowledge_bases.py` was left calling it with the OLD signature
(`session, ctx` positional + a removed `settings=` kwarg). That call is an
unconditional `TypeError` — the endpoint is dead on every request.

We patch `retrieve_docs` in the router's module with a fake that has the
*real* (new) keyword-only signature, so a caller still using the old
calling convention blows up here exactly as it would against the real
function — without needing a live DB/Qdrant/embedder stack.
"""
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk
from tfm_rag.infrastructure.api.auth_cookie import COOKIE_NAME
from tfm_rag.infrastructure.api.dependencies import get_session
from tfm_rag.infrastructure.api.middleware.tenant_scoping import (
    TenantScopingMiddleware,
)
from tfm_rag.infrastructure.api.routers import knowledge_bases
from tfm_rag.infrastructure.auth.jwt import encode_jwt
from tfm_rag.infrastructure.persistence.repositories.credentials_repo import (
    ProviderCredentialRepository,
)
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.secrets.fernet_encryptor import FernetSecretEncryptor
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


def _build_app() -> FastAPI:
    app = FastAPI()
    settings = _settings()
    app.add_middleware(TenantScopingMiddleware, settings=settings)
    app.include_router(knowledge_bases.router)

    async def _fake_session() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_settings] = lambda: settings
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


def _token(*, tenant_id, user_id) -> str:
    return encode_jwt(
        user_id=user_id, tenant_id=tenant_id, secret=SECRET,
        expires_hours=1, is_superadmin=False,
    )


async def _real_signature_fake_retrieve_docs(
    *,
    tenant_id,
    qdrant,
    dispatcher,
    kb_repo,
    credentials_repo,
    encryptor,
    ollama_base_url,
    kb_ids,
    query,
    top_k,
    score_threshold,
    reranker=None,
    reranker_initial_top_k=30,
) -> list[RetrievedChunk]:
    """Mirrors the real `retrieve_docs` keyword-only signature exactly, so an
    old-style caller (`session, ctx` positional + `settings=`) still raises
    TypeError against this fake — reproducing the bug without a live stack.
    """
    _real_signature_fake_retrieve_docs.calls.append(  # type: ignore[attr-defined]
        {
            "tenant_id": tenant_id,
            "qdrant": qdrant,
            "dispatcher": dispatcher,
            "kb_repo": kb_repo,
            "credentials_repo": credentials_repo,
            "encryptor": encryptor,
            "ollama_base_url": ollama_base_url,
            "kb_ids": kb_ids,
            "query": query,
            "top_k": top_k,
            "score_threshold": score_threshold,
        }
    )
    return [
        RetrievedChunk(
            point_id="p1",
            content="hello world",
            source_id=uuid4(),
            source_filename="doc.txt",
            chunk_index=0,
            score=0.9,
            metadata={"foo": "bar"},
        )
    ]


@pytest.fixture
def fake_retrieve_docs(monkeypatch: pytest.MonkeyPatch) -> Any:
    _real_signature_fake_retrieve_docs.calls = []  # type: ignore[attr-defined]
    monkeypatch.setattr(
        knowledge_bases, "retrieve_docs", _real_signature_fake_retrieve_docs
    )
    return _real_signature_fake_retrieve_docs


def test_search_calls_retrieve_docs_with_the_new_keyword_only_signature(
    fake_retrieve_docs: Any,
) -> None:
    """RED before the fix: the handler called `retrieve_docs(session, ctx,
    ..., settings=settings, ...)`, which is a TypeError against the real
    (and this faked) keyword-only signature. GREEN after: 200 + the
    dependencies are correctly composed and passed through.
    """
    tenant_id = uuid4()
    kb_id = uuid4()
    app = _build_app()
    client = _client(app)
    client.cookies.set(COOKIE_NAME, _token(tenant_id=tenant_id, user_id=uuid4()))

    resp = client.post(
        f"/api/knowledge-bases/{kb_id}/search",
        json={"query": "hello", "top_k": 3, "score_threshold": 0.5},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == [
        {
            "point_id": "p1",
            "content": "hello world",
            "source_id": body[0]["source_id"],
            "source_filename": "doc.txt",
            "chunk_index": 0,
            "score": 0.9,
            "metadata": {"foo": "bar"},
        }
    ]

    assert len(fake_retrieve_docs.calls) == 1
    call = fake_retrieve_docs.calls[0]
    assert call["tenant_id"] == tenant_id
    assert call["kb_ids"] == [kb_id]
    assert call["query"] == "hello"
    assert call["top_k"] == 3
    assert call["score_threshold"] == 0.5
    assert isinstance(call["kb_repo"], KnowledgeBaseRepository)
    assert isinstance(call["credentials_repo"], ProviderCredentialRepository)
    assert isinstance(call["encryptor"], FernetSecretEncryptor)
    assert call["ollama_base_url"] == "http://ollama:11434"
