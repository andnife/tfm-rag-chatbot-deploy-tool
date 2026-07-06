from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

import tfm_rag.application.chat.retrieve_docs as rd_mod
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


async def _fake_resolve_inference_target(**kwargs: Any) -> tuple[str, str, str | None]:
    """Return a fixed (provider_id, base_url, api_key) without hitting the DB."""
    return ("ollama", "http://ollama:11434", None)


def _ctx() -> RequestContext:
    return RequestContext(tenant_id=uuid4(), user_id=uuid4())


def _selection_1024(credential_id: UUID | None = None) -> EmbeddingSelection:
    return EmbeddingSelection(
        credential_id=credential_id or uuid4(),
        model_id="bge-m3",
        dim=1024,
    )


def _kb(selection: EmbeddingSelection) -> MagicMock:
    """A KnowledgeBase-entity-like fake exposing the fields retrieve_docs reads
    (`embedding_selection` is now the typed VO, not a dict)."""
    kb = MagicMock()
    kb.id = uuid4()
    kb.name = "KB"
    kb.embedding_selection = selection
    return kb


# Dummy inference deps: resolve_inference_target is monkeypatched, so these are
# only forwarded, never dereferenced.
def _deps() -> dict[str, Any]:
    return {
        "credentials_repo": MagicMock(),
        "encryptor": MagicMock(),
        "ollama_base_url": "http://ollama:11434",
    }


@pytest.mark.asyncio
async def test_retrieve_docs_embeds_query_and_searches_qdrant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rd_mod, "resolve_inference_target", _fake_resolve_inference_target)
    ctx = _ctx()
    selection = _selection_1024()
    kb = _kb(selection)

    kb_repo = MagicMock()
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb)

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
                    "kb_id": str(kb.id),
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
                    "kb_id": str(kb.id),
                    "source_id": str(src_b),
                    "chunk_index": 0,
                    "content": "beta",
                    "source_filename": "beta.txt",
                },
            ),
        ]
    )

    chunks = await retrieve_docs(
        tenant_id=ctx.tenant_id,
        qdrant=qdrant,
        dispatcher=dispatcher,
        kb_repo=kb_repo,
        **_deps(),
        kb_ids=[kb.id],
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
    assert qcall.kwargs["kb_ids"] == [kb.id]
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

    chunks = await retrieve_docs(
        tenant_id=ctx.tenant_id,
        qdrant=qdrant, dispatcher=dispatcher, kb_repo=kb_repo, **_deps(),
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
    kb_repo.get_knowledge_base = AsyncMock(side_effect=NotFoundError("nope"))
    dispatcher = MagicMock()
    qdrant = MagicMock()

    with pytest.raises(KnowledgeBaseNotFoundError):
        await retrieve_docs(
            tenant_id=ctx.tenant_id,
            qdrant=qdrant, dispatcher=dispatcher, kb_repo=kb_repo, **_deps(),
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
        credential_id=uuid4(),
        model_id="nomic-embed-text",
        dim=768,
    )
    kb_a = _kb(sel_1024)
    kb_b = _kb(sel_768)
    kb_repo = MagicMock()
    kb_repo.get_knowledge_base = AsyncMock(side_effect=[kb_a, kb_b])

    dispatcher = MagicMock()
    qdrant = MagicMock()

    with pytest.raises(IncompatibleEmbeddingsError):
        await retrieve_docs(
            tenant_id=ctx.tenant_id,
            qdrant=qdrant, dispatcher=dispatcher, kb_repo=kb_repo, **_deps(),
            kb_ids=[kb_a.id, kb_b.id],
            query="hi",
            top_k=5,
            score_threshold=None,
        )


@pytest.mark.asyncio
async def test_retrieve_docs_unsupported_provider_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the dispatcher raises UnsupportedProviderError the use case lets it bubble."""
    monkeypatch.setattr(rd_mod, "resolve_inference_target", _fake_resolve_inference_target)
    ctx = _ctx()
    sel_alien = EmbeddingSelection.from_dict({
        "provider_id": "openai_compat",
        "credential_id": str(uuid4()),
        "model_id": "text-embedding-3-small",
        "dim": 1536,
    })
    kb = _kb(sel_alien)
    kb_repo = MagicMock()
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb)
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(
        side_effect=UnsupportedProviderError("no openai_compat")
    )
    qdrant = MagicMock()
    qdrant.search = AsyncMock()

    with pytest.raises(UnsupportedProviderError):
        await retrieve_docs(
            tenant_id=ctx.tenant_id,
            qdrant=qdrant, dispatcher=dispatcher, kb_repo=kb_repo, **_deps(),
            kb_ids=[kb.id],
            query="hi",
            top_k=5,
            score_threshold=None,
        )
    qdrant.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_retrieve_docs_applies_reranker_when_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rd_mod, "resolve_inference_target", _fake_resolve_inference_target)
    ctx = _ctx()
    selection = _selection_1024()
    kb = _kb(selection)
    kb_repo = MagicMock()
    kb_repo.get_knowledge_base = AsyncMock(return_value=kb)

    embedder = MagicMock()
    embedder.embed = AsyncMock(return_value=[[0.1] * 1024])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=embedder)

    qdrant = MagicMock()
    src = uuid4()
    qdrant.search = AsyncMock(
        return_value=[
            ("pid-A", 0.50, {
                "tenant_id": str(ctx.tenant_id), "kb_id": str(kb.id),
                "source_id": str(src), "chunk_index": 0,
                "content": "low rank", "source_filename": "x.txt",
            }),
            ("pid-B", 0.40, {
                "tenant_id": str(ctx.tenant_id), "kb_id": str(kb.id),
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

    chunks = await retrieve_docs(
        tenant_id=ctx.tenant_id,
        qdrant=qdrant, dispatcher=dispatcher, kb_repo=kb_repo, **_deps(),
        kb_ids=[kb.id],
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
