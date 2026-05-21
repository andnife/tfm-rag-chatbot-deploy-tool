# CAP-CHAT-DOC-RETRIEVAL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Ship `RetrieveDocs(kb_ids, query, top_k, threshold) → list[RetrievedChunk]` — the search side of M3. The use case is reachable today via a utility endpoint `POST /api/knowledge-bases/{kb_id}/search` so we can test it end-to-end without waiting for the agent loop (plan #15). It will become a tool of the agent loop in #15.

**Architecture:**
- Domain VO `RetrievedChunk` (id, content, source_id, source_filename, score, metadata) returned by both Qdrant and Reranker.
- Domain port `Reranker` (stub for now; no adapters in this plan — `BGECrossEncoderReranker` and `CohereRerankerAdapter` are deferred).
- `infrastructure/embedders/dispatcher.py` `EmbedderDispatcher`: looks up an `Embedder` by `provider_id`. Plan #12 ships only the Ollama entry; TENANT_CREDENTIAL providers (openai_compat) are deferred.
- `QdrantStore` gains a `search` method that runs the vector search with a `tenant_id + kb_id IN (...)` filter and returns the raw payload + score per hit.
- One use case: `retrieve_docs(...)`. Tenant-scoped via the KB repo. If `use_reranker=True` is requested but no `Reranker` is wired, the function emits a warning and degrades gracefully (no reranking).
- One utility endpoint `POST /api/knowledge-bases/{kb_id}/search` (NOT in the spec API table — it's a debugging/demo endpoint to verify the pipeline works before the agent loop arrives in #15; small surface area, useful for the frontend's "search only" UX).

**Tech Stack:** No new deps. Reuses `OllamaEmbedder`, `QdrantStore`, `EmbeddingSelection`.

**Depends on:** plan #7 (KB + `EmbeddingSelection`), plan #8 (`OllamaEmbedder`, Qdrant ingestion → there must be chunks to retrieve).

**Out of scope (deferred):**
- Reranker adapters (BGE / Cohere) → later plan. The port stays unregistered; `enable_reranker=true` without an injected reranker just logs a warning.
- `openai_compat` Embedder adapter → later. Plan #12's dispatcher only registers Ollama. If a KB declares an embedding under a different provider, `RetrieveDocs` raises `UnsupportedProviderError`.
- Search-via-chatbot (`POST /api/chatbots/{id}/chat`) and the SSE stream → plan #15. Today we expose retrieval through the KB.
- Multi-KB retrieval as part of one call: supported by the use case (`kb_ids: list[UUID]`) but the route only takes a single `kb_id` from the path. The agent loop in #15 will exercise the multi-KB path against a chatbot's attached set.

---

## File structure

```
backend/src/tfm_rag/
├── domain/
│   ├── value_objects/
│   │   └── retrieved_chunk.py            # NEW
│   ├── ports/
│   │   └── reranker.py                   # NEW (stub Protocol)
│   └── errors/
│       └── chat.py                       # NEW (UnsupportedProviderError, RetrievalError)
│
├── infrastructure/
│   ├── embedders/
│   │   └── dispatcher.py                 # NEW (EmbedderDispatcher)
│   └── vector_store/
│       └── qdrant_client.py              # MODIFY: +search method
│
└── application/
    └── chat/
        ├── __init__.py                   # NEW (empty)
        └── retrieve_docs.py              # NEW

backend/src/tfm_rag/infrastructure/api/routers/
└── knowledge_bases.py                    # MODIFY: +POST /{kb_id}/search

backend/tests/unit/
├── test_retrieved_chunk.py               # NEW (small)
├── test_embedder_dispatcher.py           # NEW
└── test_retrieve_docs.py                 # NEW (with fakes)

backend/tests/integration/
└── test_retrieve_docs_flow.py            # NEW (upload → ingest → search → assert hits)
```

---

## Task 1 — Domain: VO + Reranker port + errors

**Files:**
- Create: `backend/src/tfm_rag/domain/value_objects/retrieved_chunk.py`
- Create: `backend/src/tfm_rag/domain/ports/reranker.py`
- Create: `backend/src/tfm_rag/domain/errors/chat.py`
- Create: `backend/tests/unit/test_retrieved_chunk.py`

- [ ] **Step 1.1: Create `backend/src/tfm_rag/domain/value_objects/retrieved_chunk.py`**

```python
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """One result from vector search. Shape returned by both Qdrant and Reranker.

    `point_id` is the Qdrant point id (a UUIDv5 derived from
    `(source_id, chunk_index)` — see plan #8 `_point_id`).
    `metadata` carries the rest of the payload that's not promoted to fields
    (e.g. `chunk_start`, `chunk_end`, `kb_id`).
    """

    point_id: str
    content: str
    source_id: UUID
    source_filename: str
    chunk_index: int
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 1.2: Create `backend/src/tfm_rag/domain/ports/reranker.py`**

```python
from typing import Protocol

from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk


class Reranker(Protocol):
    """Reorders / trims a list of candidates by relevance to `query`.

    Plan #12 ships the port only. Adapters (`BGECrossEncoderReranker`,
    `CohereRerankerAdapter`) land in a later plan. If `enable_reranker=true`
    is requested but no Reranker is wired, `retrieve_docs` degrades to
    a no-op rerank and emits a warning.
    """

    async def rerank(
        self,
        *,
        query: str,
        candidates: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]: ...
```

- [ ] **Step 1.3: Create `backend/src/tfm_rag/domain/errors/chat.py`**

```python
from tfm_rag.domain.errors.common import DomainError


class UnsupportedProviderError(DomainError):
    """Raised when retrieve_docs is asked to embed with a provider whose
    Embedder adapter hasn't been wired yet. Plan #12 only supports Ollama.
    """


class RetrievalError(DomainError):
    """Raised when the retrieval pipeline (embed + vector search) fails for
    a reason that isn't tenant-scope, not-found, or validation.
    """
```

- [ ] **Step 1.4: Write the failing test + run it**

Create `backend/tests/unit/test_retrieved_chunk.py`:

```python
from uuid import uuid4

from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk


def test_retrieved_chunk_is_hashable_via_frozen_dataclass() -> None:
    src = uuid4()
    c = RetrievedChunk(
        point_id="p1",
        content="hello",
        source_id=src,
        source_filename="x.txt",
        chunk_index=0,
        score=0.92,
        metadata={"chunk_start": 0},
    )
    # frozen=True → can be put in a set
    assert {c, c} == {c}
    assert c.score == 0.92


def test_retrieved_chunk_default_metadata_is_empty() -> None:
    c = RetrievedChunk(
        point_id="p1",
        content="hello",
        source_id=uuid4(),
        source_filename="x.txt",
        chunk_index=0,
        score=1.0,
    )
    assert c.metadata == {}
```

Run:
```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
pytest tests/unit/test_retrieved_chunk.py -v
```

Expected: **2 PASSED** (the test file imports a module you just created — should not fail collection).

- [ ] **Step 1.5: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/domain/value_objects/retrieved_chunk.py backend/src/tfm_rag/domain/ports/reranker.py backend/src/tfm_rag/domain/errors/chat.py backend/tests/unit/test_retrieved_chunk.py
git commit -m "feat(domain): RetrievedChunk VO + Reranker port + chat errors"
```

---

## Task 2 — Infrastructure: EmbedderDispatcher + `QdrantStore.search`

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/embedders/dispatcher.py`
- Modify: `backend/src/tfm_rag/infrastructure/vector_store/qdrant_client.py` (add `search` method)
- Create: `backend/tests/unit/test_embedder_dispatcher.py`

- [ ] **Step 2.1: Write the failing test for the dispatcher**

Create `backend/tests/unit/test_embedder_dispatcher.py`:

```python
import pytest

from tfm_rag.domain.errors.chat import UnsupportedProviderError
from tfm_rag.infrastructure.embedders.dispatcher import EmbedderDispatcher
from tfm_rag.infrastructure.embedders.ollama import OllamaEmbedder


def test_dispatcher_returns_ollama_for_ollama_provider() -> None:
    d = EmbedderDispatcher.default()
    emb = d.for_provider("ollama")
    assert isinstance(emb, OllamaEmbedder)


def test_dispatcher_raises_for_unknown_provider() -> None:
    d = EmbedderDispatcher.default()
    with pytest.raises(UnsupportedProviderError, match="openai_compat"):
        d.for_provider("openai_compat")


def test_dispatcher_accepts_custom_registry() -> None:
    sentinel = OllamaEmbedder()
    d = EmbedderDispatcher({"custom": sentinel})
    assert d.for_provider("custom") is sentinel
    with pytest.raises(UnsupportedProviderError):
        d.for_provider("ollama")
```

Run, confirm collection error (module not found):
```bash
pytest tests/unit/test_embedder_dispatcher.py -v
```

- [ ] **Step 2.2: Create `backend/src/tfm_rag/infrastructure/embedders/dispatcher.py`**

```python
from tfm_rag.domain.errors.chat import UnsupportedProviderError
from tfm_rag.domain.ports.embedder import Embedder
from tfm_rag.infrastructure.embedders.ollama import OllamaEmbedder


class EmbedderDispatcher:
    """Routes (`provider_id` → `Embedder`).

    Plan #12 wires only `ollama`. A later plan will register `openai_compat`
    once the OpenAIEmbedder adapter exists.
    """

    def __init__(self, registry: dict[str, Embedder]) -> None:
        self._registry = registry

    def for_provider(self, provider_id: str) -> Embedder:
        emb = self._registry.get(provider_id)
        if emb is None:
            raise UnsupportedProviderError(
                f"No Embedder registered for provider_id={provider_id!r}. "
                f"Available: {sorted(self._registry)}"
            )
        return emb

    @classmethod
    def default(cls) -> "EmbedderDispatcher":
        return cls({"ollama": OllamaEmbedder()})
```

- [ ] **Step 2.3: Run the dispatcher test, expect 3 PASSED**

```bash
pytest tests/unit/test_embedder_dispatcher.py -v
```

Expected: **3 PASSED**.

- [ ] **Step 2.4: Extend `QdrantStore` with a `search` method**

Open `backend/src/tfm_rag/infrastructure/vector_store/qdrant_client.py`. Add `MatchAny` to the imports from `qdrant_client.models` if not already there. Then add the `search` method to the `QdrantStore` class, placed right after `delete_by_source`:

```python
    async def search(
        self,
        *,
        collection: str,
        tenant_id: UUID,
        kb_ids: list[UUID],
        query_vector: list[float],
        top_k: int,
        score_threshold: float | None = None,
    ) -> list[tuple[str, float, dict[str, Any]]]:
        """Run vector search filtered by tenant_id + kb_ids.

        Returns a list of `(point_id, score, payload)` tuples sorted by score
        descending. `score_threshold` is applied as a `score_threshold`
        argument to Qdrant (server-side filter).
        """
        if not kb_ids:
            return []
        kb_ids_str = [str(k) for k in kb_ids]
        result = await self._client.search(
            collection_name=collection,
            query_vector=query_vector,
            limit=top_k,
            score_threshold=score_threshold,
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="tenant_id",
                        match=MatchValue(value=str(tenant_id)),
                    ),
                    FieldCondition(
                        key="kb_id",
                        match=MatchAny(any=kb_ids_str),
                    ),
                ]
            ),
            with_payload=True,
        )
        out: list[tuple[str, float, dict[str, Any]]] = []
        for hit in result:
            out.append((str(hit.id), float(hit.score), dict(hit.payload or {})))
        return out
```

Add `MatchAny` to the top-of-file import block:

```python
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)
```

- [ ] **Step 2.5: Verify `QdrantStore` still imports cleanly**

```bash
python -c "from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore; print(QdrantStore)"
```

Expected: prints the class. No ImportError.

- [ ] **Step 2.6: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/infrastructure/embedders/dispatcher.py backend/src/tfm_rag/infrastructure/vector_store/qdrant_client.py backend/tests/unit/test_embedder_dispatcher.py
git commit -m "feat(infra): EmbedderDispatcher + QdrantStore.search (kb_ids filter)"
```

---

## Task 3 — Application: `retrieve_docs` use case + unit tests

**Files:**
- Create: `backend/src/tfm_rag/application/chat/__init__.py` (empty)
- Create: `backend/src/tfm_rag/application/chat/retrieve_docs.py`
- Create: `backend/tests/unit/test_retrieve_docs.py`

- [ ] **Step 3.1: Write the failing unit test**

Create `backend/tests/unit/test_retrieve_docs.py`:

```python
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
```

Run, confirm collection error (module not found yet):
```bash
pytest tests/unit/test_retrieve_docs.py -v
```

- [ ] **Step 3.2: Create `backend/src/tfm_rag/application/chat/__init__.py`** (empty)

- [ ] **Step 3.3: Create `backend/src/tfm_rag/application/chat/retrieve_docs.py`**

```python
import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import (
    IncompatibleEmbeddingsError,
    KnowledgeBaseNotFoundError,
)
from tfm_rag.domain.ports.reranker import Reranker
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk
from tfm_rag.infrastructure.embedders.dispatcher import EmbedderDispatcher
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.settings import Settings
from tfm_rag.infrastructure.vector_store.qdrant_client import (
    QdrantStore,
    collection_name_for,
)

_log = logging.getLogger(__name__)

KbRepoFactory = Callable[
    [AsyncSession, RequestContext], KnowledgeBaseRepository
]


def _default_kb_repo(
    session: AsyncSession, ctx: RequestContext
) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session, ctx)


_PAYLOAD_PROMOTED_KEYS: frozenset[str] = frozenset(
    {"tenant_id", "kb_id", "source_id", "chunk_index", "content", "source_filename"}
)


def _hit_to_chunk(point_id: str, score: float, payload: dict[str, Any]) -> RetrievedChunk:
    """Translate a raw Qdrant hit into a domain RetrievedChunk."""
    return RetrievedChunk(
        point_id=point_id,
        content=str(payload.get("content", "")),
        source_id=UUID(str(payload["source_id"])),
        source_filename=str(payload.get("source_filename", "")),
        chunk_index=int(payload.get("chunk_index", 0)),
        score=score,
        metadata={
            k: v for k, v in payload.items() if k not in _PAYLOAD_PROMOTED_KEYS
        },
    )


async def _load_and_validate_kbs(
    kb_repo: KnowledgeBaseRepository, kb_ids: list[UUID]
) -> EmbeddingSelection:
    """Load each KB, enforce they share embedding_selection. Returns the
    shared selection.
    """
    selections: list[EmbeddingSelection] = []
    for kb_id in kb_ids:
        try:
            kb_row = await kb_repo.get(kb_id)
        except NotFoundError as exc:
            raise KnowledgeBaseNotFoundError(str(exc)) from exc
        selections.append(EmbeddingSelection.from_dict(kb_row.embedding_selection))
    first = selections[0]
    for other in selections[1:]:
        if other != first:
            raise IncompatibleEmbeddingsError(
                "Attached KBs disagree on embedding_selection. "
                f"Got {first.to_dict()} and {other.to_dict()}."
            )
    return first


async def retrieve_docs(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    qdrant: QdrantStore,
    dispatcher: EmbedderDispatcher,
    settings: Settings,
    kb_repo_factory: KbRepoFactory = _default_kb_repo,
    kb_ids: list[UUID],
    query: str,
    top_k: int,
    score_threshold: float | None,
    reranker: Reranker | None = None,
    reranker_initial_top_k: int = 30,
) -> list[RetrievedChunk]:
    """Embed `query`, vector-search Qdrant filtered by tenant_id + kb_ids,
    optionally rerank, return the top_k chunks.

    Raises:
      - KnowledgeBaseNotFoundError if any kb_id is missing in the tenant.
      - IncompatibleEmbeddingsError if the KBs disagree on embedding_selection.
      - UnsupportedProviderError if the embedder dispatcher has no entry for
        the selection's provider.
    """
    if not query.strip():
        return []
    if not kb_ids:
        return []

    kb_repo = kb_repo_factory(session, ctx)
    selection = await _load_and_validate_kbs(kb_repo, kb_ids)

    # Plan #12 only wires Ollama. base_url comes from settings (SERVER_ENV).
    # Once TENANT_CREDENTIAL providers are added, we'll decrypt the
    # credential row indicated by selection.credential_id.
    embedder = dispatcher.for_provider(selection.provider_id)
    base_url = settings.ollama_base_url  # only Ollama path today

    vectors = await embedder.embed(
        base_url=base_url,
        api_key=None,
        model_id=selection.model_id,
        texts=[query],
    )
    query_vec = vectors[0]

    collection = collection_name_for(ctx.tenant_id, selection.dim)
    search_top_k = reranker_initial_top_k if reranker is not None else top_k
    hits = await qdrant.search(
        collection=collection,
        tenant_id=ctx.tenant_id,
        kb_ids=kb_ids,
        query_vector=query_vec,
        top_k=search_top_k,
        score_threshold=score_threshold,
    )

    chunks = [_hit_to_chunk(pid, score, payload) for pid, score, payload in hits]

    if reranker is not None:
        chunks = await reranker.rerank(query=query, candidates=chunks, top_k=top_k)
    else:
        chunks = chunks[:top_k]

    return chunks
```

- [ ] **Step 3.4: Run the retrieve_docs tests, expect 6 PASSED**

```bash
pytest tests/unit/test_retrieve_docs.py -v
```

Expected: **6 PASSED**.

- [ ] **Step 3.5: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/application/chat backend/tests/unit/test_retrieve_docs.py
git commit -m "feat(chat): retrieve_docs use case (embed + Qdrant search + optional reranker)"
```

---

## Task 4 — API: `POST /api/knowledge-bases/{kb_id}/search`

This is a utility endpoint not in the spec API table (the spec routes retrieval through the agent loop). We add it now so the M3 demo path is testable end-to-end before plan #15 lands. It also gives the frontend a "search only" mode out of the box.

**Files:**
- Modify: `backend/src/tfm_rag/infrastructure/api/routers/knowledge_bases.py` (add `POST /{kb_id}/search`)

- [ ] **Step 4.1: Append the search endpoint to `knowledge_bases.py`**

Add these imports to the top of the file (merge with existing imports, do not duplicate):

```python
from tfm_rag.application.chat.retrieve_docs import retrieve_docs
from tfm_rag.domain.errors.chat import UnsupportedProviderError
from tfm_rag.domain.errors.knowledge import IncompatibleEmbeddingsError
from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk
from tfm_rag.infrastructure.embedders.dispatcher import EmbedderDispatcher
```

Then add the request/response models and the route at the bottom of the file:

```python
class SearchIn(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=50)
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class SearchHitOut(BaseModel):
    point_id: str
    content: str
    source_id: str
    source_filename: str
    chunk_index: int
    score: float
    metadata: dict[str, Any]

    @classmethod
    def from_chunk(cls, c: RetrievedChunk) -> "SearchHitOut":
        return cls(
            point_id=c.point_id,
            content=c.content,
            source_id=str(c.source_id),
            source_filename=c.source_filename,
            chunk_index=c.chunk_index,
            score=c.score,
            metadata=c.metadata,
        )


@router.post("/{kb_id}/search", response_model=list[SearchHitOut])
async def search_(
    kb_id: UUID,
    body: SearchIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> list[SearchHitOut]:
    qdrant = _qdrant(settings)
    try:
        chunks = await retrieve_docs(
            session, ctx,
            qdrant=qdrant,
            dispatcher=EmbedderDispatcher.default(),
            settings=settings,
            kb_ids=[kb_id],
            query=body.query,
            top_k=body.top_k,
            score_threshold=body.score_threshold,
        )
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except IncompatibleEmbeddingsError as exc:
        # Cannot happen for a single kb_id, but keep the mapping for symmetry.
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except UnsupportedProviderError as exc:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)
        ) from exc
    finally:
        await qdrant.close()
    return [SearchHitOut.from_chunk(c) for c in chunks]
```

- [ ] **Step 4.2: Verify app imports cleanly**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
python -c "from tfm_rag.infrastructure.api.app import app; print(app.title)"
```

Expected: prints `TFM RAG Chatbot Platform`.

- [ ] **Step 4.3: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/infrastructure/api/routers/knowledge_bases.py
git commit -m "feat(api): POST /api/knowledge-bases/{kb_id}/search (retrieve_docs utility endpoint)"
```

---

## Task 5 — Integration test: end-to-end search after ingestion

We exercise the full M3 retrieval path against the live stack: register → create KB → upload TXT → poll until ingested → search → verify the matching chunk comes back top of the list.

**Files:**
- Create: `backend/tests/integration/test_retrieve_docs_flow.py`

- [ ] **Step 5.1: Write the integration test**

Create `backend/tests/integration/test_retrieve_docs_flow.py`:

```python
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
            "Pineapples are tropical fruit that grow on a low plant. "
            "They are sweet and acidic. Many people enjoy pineapple slices "
            "with ham on pizza, which is famously controversial.\n\n"
            "Typewriters are mechanical writing machines that became popular "
            "in offices in the late 19th and early 20th centuries. They use "
            "a ribbon of inked fabric to imprint letters onto paper."
        ).encode("utf-8")
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
```

- [ ] **Step 5.2: Reset DB and run the new integration test**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
docker exec tfm-rag-postgres-1 psql -U tfm -d tfm_rag \
  -c "DROP TABLE IF EXISTS chatbot_knowledge_base, chatbots, ingestion_jobs, sources, knowledge_bases, provider_credentials, users, tenants, alembic_version CASCADE;"
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
alembic upgrade head
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
pytest tests/integration/test_retrieve_docs_flow.py -m integration -v
```

Expected: **3 PASSED**. The first test does real ingestion through Ollama; it may take up to ~30s.

- [ ] **Step 5.3: Run the full integration suite to confirm no regressions**

```bash
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
pytest tests/integration -m integration -v
```

Expected: previous 17 + 3 retrieval tests = **20 PASSED**.

- [ ] **Step 5.4: Commit + tag**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/tests/integration/test_retrieve_docs_flow.py
git commit -m "test(chat): end-to-end retrieve_docs flow (upload → ingest → search → assert top hit)"
git tag cap-12-chat-doc-retrieval
```

---

## What's next (deferred, for handover)

After this plan ships:

- **Plan #14 (CAP-CHAT-SESSIONS)** adds the `chat_sessions` + `chat_messages` tables and the session/message persistence use cases. This is a prereq for plan #15.
- **Plan #15 (CAP-CHAT-AGENT-LOOP / AnswerQuery)** is the glue: takes a chatbot's `llm_selection` + `pipeline_config`, runs the agentic loop over the attached KBs (calling `retrieve_docs` as a tool), persists `RetrievalIteration[]` in `ChatMessage.metadata`, and exposes `POST /api/chatbots/{chatbot_id}/chat` with SSE streaming. After #15 the M3 demo is complete: a user creates a chatbot, attaches the M2 KB, asks a question in the playground, and gets a cited answer.
- **Reranker adapters** (`BGECrossEncoderReranker`, `CohereRerankerAdapter`) can land in a small horizontal plan whenever; `retrieve_docs` already accepts a `Reranker` instance.
- **`openai_compat` Embedder** can land in a horizontal plan; just register it in `EmbedderDispatcher.default()`. Until then, KBs created with that provider will fail `RetrieveDocs` with `UnsupportedProviderError` (HTTP 501).
