from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from tfm_rag.application.chat.retrieve_docs import retrieve_docs
from tfm_rag.domain.errors.chat import UnsupportedProviderError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import (
    IncompatibleEmbeddingsError,
    KnowledgeBaseNotFoundError,
)
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk
from tfm_rag.infrastructure.persistence.repository import RequestContext


def _ctx() -> RequestContext:
    return RequestContext(tenant_id=uuid4(), user_id=uuid4())


def _selection_1024(credential_id: UUID | None = None) -> EmbeddingSelection:
    return EmbeddingSelection(
        provider_id="ollama",
        credential_id=credential_id or uuid4(),
        model_id="bge-m3",
        dim=1024,
    )


def _kb_row(selection: EmbeddingSelection) -> MagicMock:
    row = MagicMock()
    row.id = uuid4()
    row.embedding_selection = selection.to_dict()
    return row


def _fake_settings(ollama_base_url: str = "http://ollama:11434") -> MagicMock:
    s = MagicMock()
    s.ollama_base_url = ollama_base_url
    return s


@pytest.mark.asyncio
async def test_retrieve_docs_embeds_query_and_searches_qdrant() -> None:
    ctx = _ctx()
    selection = _selection_1024()
    kb_row = _kb_row(selection)

    kb_repo = MagicMock()
    kb_repo.get = AsyncMock(return_value=kb_row)

    embedder = MagicMock()
    embedder.embed = AsyncMock(return_value=[[0.1] * 1024])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=embedder)

    qdrant = MagicMock()
    src_a, src_b = uuid4(), uuid4()
    qdrant.search = AsyncMock(
        return_value=[
            (
                "pid-1",
                0.91,
                {
                    "tenant_id": str(ctx.tenant_id),
                    "kb_id": str(kb_row.id),
                    "source_id": str(src_a),
                    "chunk_index": 0,
                    "content": "alpha",
                    "source_filename": "alpha.txt",
                    "chunk_start": 0,
                },
            ),
            (
                "pid-2",
                0.83,
                {
                    "tenant_id": str(ctx.tenant_id),
                    "kb_id": str(kb_row.id),
                    "source_id": str(src_b),
                    "chunk_index": 0,
                    "content": "beta",
                    "source_filename": "beta.txt",
                },
            ),
        ]
    )

    session = MagicMock()

    chunks = await retrieve_docs(
        session,
        ctx,
        qdrant=qdrant,
        dispatcher=dispatcher,
        settings=_fake_settings(),
        kb_repo_factory=lambda s, c: kb_repo,
        kb_ids=[kb_row.id],
        query="what is alpha?",
        top_k=5,
        score_threshold=None,
    )

    embedder.embed.assert_awaited_once()
    # Inspect the call: model_id should be the KB's selection.model_id
    call = embedder.embed.await_args
    assert call.kwargs["model_id"] == "bge-m3"
    assert call.kwargs["texts"] == ["what is alpha?"]
    assert call.kwargs["base_url"] == "http://ollama:11434"

    qdrant.search.assert_awaited_once()
    qcall = qdrant.search.await_args
    assert qcall.kwargs["tenant_id"] == ctx.tenant_id
    assert qcall.kwargs["kb_ids"] == [kb_row.id]
    assert qcall.kwargs["top_k"] == 5
    assert qcall.kwargs["score_threshold"] is None

    assert len(chunks) == 2
    assert all(isinstance(c, RetrievedChunk) for c in chunks)
    assert chunks[0].content == "alpha"
    assert chunks[0].source_id == src_a
    assert chunks[0].source_filename == "alpha.txt"
    assert chunks[0].chunk_index == 0
    assert chunks[0].score == 0.91
    # metadata carries non-promoted payload keys (chunk_start was there)
    assert chunks[0].metadata.get("chunk_start") == 0


@pytest.mark.asyncio
async def test_retrieve_docs_returns_empty_when_query_is_empty() -> None:
    ctx = _ctx()
    kb_repo = MagicMock()
    dispatcher = MagicMock()
    qdrant = MagicMock()
    qdrant.search = AsyncMock()
    session = MagicMock()

    chunks = await retrieve_docs(
        session, ctx,
        qdrant=qdrant, dispatcher=dispatcher, settings=_fake_settings(),
        kb_repo_factory=lambda s, c: kb_repo,
        kb_ids=[uuid4()],
        query="   ",
        top_k=5,
        score_threshold=None,
    )

    assert chunks == []
    qdrant.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_retrieve_docs_raises_when_kb_missing() -> None:
    ctx = _ctx()
    kb_repo = MagicMock()
    kb_repo.get = AsyncMock(side_effect=NotFoundError("nope"))
    dispatcher = MagicMock()
    qdrant = MagicMock()
    session = MagicMock()

    with pytest.raises(KnowledgeBaseNotFoundError):
        await retrieve_docs(
            session, ctx,
            qdrant=qdrant, dispatcher=dispatcher, settings=_fake_settings(),
            kb_repo_factory=lambda s, c: kb_repo,
            kb_ids=[uuid4()],
            query="hi",
            top_k=5,
            score_threshold=None,
        )


@pytest.mark.asyncio
async def test_retrieve_docs_rejects_incompatible_embeddings_across_kbs() -> None:
    ctx = _ctx()
    sel_1024 = _selection_1024()
    sel_768 = EmbeddingSelection(
        provider_id="ollama", credential_id=uuid4(),
        model_id="nomic-embed-text", dim=768,
    )
    kb_a = _kb_row(sel_1024)
    kb_b = _kb_row(sel_768)
    kb_repo = MagicMock()
    kb_repo.get = AsyncMock(side_effect=[kb_a, kb_b])

    dispatcher = MagicMock()
    qdrant = MagicMock()
    session = MagicMock()

    with pytest.raises(IncompatibleEmbeddingsError):
        await retrieve_docs(
            session, ctx,
            qdrant=qdrant, dispatcher=dispatcher, settings=_fake_settings(),
            kb_repo_factory=lambda s, c: kb_repo,
            kb_ids=[kb_a.id, kb_b.id],
            query="hi",
            top_k=5,
            score_threshold=None,
        )


@pytest.mark.asyncio
async def test_retrieve_docs_unsupported_provider_propagates() -> None:
    """Plan #12 only registers ollama. If the KB declares another provider
    the dispatcher raises UnsupportedProviderError and the use case lets it
    bubble.
    """
    ctx = _ctx()
    sel_alien = EmbeddingSelection.from_dict({
        "provider_id": "openai_compat",
        "credential_id": str(uuid4()),
        "model_id": "text-embedding-3-small",
        "dim": 1536,
    })
    kb_row = _kb_row(sel_alien)
    kb_repo = MagicMock()
    kb_repo.get = AsyncMock(return_value=kb_row)
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(
        side_effect=UnsupportedProviderError("no openai_compat")
    )
    qdrant = MagicMock()
    qdrant.search = AsyncMock()
    session = MagicMock()

    with pytest.raises(UnsupportedProviderError):
        await retrieve_docs(
            session, ctx,
            qdrant=qdrant, dispatcher=dispatcher, settings=_fake_settings(),
            kb_repo_factory=lambda s, c: kb_repo,
            kb_ids=[kb_row.id],
            query="hi",
            top_k=5,
            score_threshold=None,
        )
    qdrant.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_retrieve_docs_applies_reranker_when_provided() -> None:
    ctx = _ctx()
    selection = _selection_1024()
    kb_row = _kb_row(selection)
    kb_repo = MagicMock()
    kb_repo.get = AsyncMock(return_value=kb_row)

    embedder = MagicMock()
    embedder.embed = AsyncMock(return_value=[[0.1] * 1024])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=embedder)

    qdrant = MagicMock()
    src = uuid4()
    qdrant.search = AsyncMock(
        return_value=[
            ("pid-A", 0.50, {
                "tenant_id": str(ctx.tenant_id), "kb_id": str(kb_row.id),
                "source_id": str(src), "chunk_index": 0,
                "content": "low rank", "source_filename": "x.txt",
            }),
            ("pid-B", 0.40, {
                "tenant_id": str(ctx.tenant_id), "kb_id": str(kb_row.id),
                "source_id": str(src), "chunk_index": 1,
                "content": "high after rerank", "source_filename": "x.txt",
            }),
        ]
    )

    # Reranker swaps the order
    reranker = MagicMock()

    async def _rerank(*, query: str, candidates: list, top_k: int) -> list[Any]:
        # Reverse + top_k=1 → only the previously-second candidate survives
        return list(reversed(candidates))[:top_k]

    reranker.rerank = AsyncMock(side_effect=_rerank)
    session = MagicMock()

    chunks = await retrieve_docs(
        session, ctx,
        qdrant=qdrant, dispatcher=dispatcher, settings=_fake_settings(),
        kb_repo_factory=lambda s, c: kb_repo,
        kb_ids=[kb_row.id],
        query="?",
        top_k=1,
        score_threshold=None,
        reranker=reranker,
        reranker_initial_top_k=10,
    )

    # Reranker received the full Qdrant list (top_k=10) and trimmed to 1
    reranker.rerank.assert_awaited_once()
    assert len(chunks) == 1
    assert chunks[0].content == "high after rerank"

    # Qdrant was called with the *initial* top_k (10), not the final (1)
    qcall = qdrant.search.await_args
    assert qcall.kwargs["top_k"] == 10
