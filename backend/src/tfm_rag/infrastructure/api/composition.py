"""Composition root — the single place dependency graphs are wired.

Routers and background jobs get their repositories, adapters and use-case
dependency bundles from here instead of instantiating them inline. Two flavours
are provided:

* **FastAPI ``Depends`` providers** (``get_*_repo``, ``get_qdrant`` …) for the
  request-scoped path. FastAPI caches each dependency within a request, so all
  repos built via these providers share the one request session.
* **Plain builder functions** (``build_answer_query_deps``, ``build_*_repo``)
  for background jobs, which run with a *fresh* session per job (the eval run
  job and the ingestion scheduler each open their own session) and cannot use
  ``Depends``.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.chat.query_database import (
    QueryDatabaseInput,
    QueryDatabaseOutput,
    query_database,
)
from tfm_rag.domain.ports.secret_encryptor import SecretEncryptor
from tfm_rag.infrastructure.api.dependencies import (
    get_current_context,
    get_session,
)
from tfm_rag.infrastructure.database_connectors import DATABASE_CONNECTORS
from tfm_rag.infrastructure.embedders.dispatcher import EmbedderDispatcher
from tfm_rag.infrastructure.llm_providers.dispatcher import LLMDispatcher
from tfm_rag.infrastructure.persistence.repositories.chat_sessions_repo import (
    ChatMessageRepository,
    ChatSessionRepository,
)
from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
    ChatbotRepository,
)
from tfm_rag.infrastructure.persistence.repositories.credentials_repo import (
    ProviderCredentialRepository,
)
from tfm_rag.infrastructure.persistence.repositories.eval_datasets_repo import (
    EvalDatasetItemRepository,
    EvalDatasetRepository,
)
from tfm_rag.infrastructure.persistence.repositories.eval_runs_repo import (
    EvalRunRepository,
)
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repositories.sources_repo import (
    SourceRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.secrets.fernet_encryptor import FernetSecretEncryptor
from tfm_rag.infrastructure.settings import Settings, get_settings
from tfm_rag.infrastructure.storage.local import LocalStorage
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore

# ---------------------------------------------------------------------------
# Plain builders (session-factory-aware; usable by background jobs)
# ---------------------------------------------------------------------------


def make_query_database_fn(
    session: AsyncSession, encryptor: SecretEncryptor
) -> Callable[..., Awaitable[QueryDatabaseOutput]]:
    """Bind the SQL executor's infra dependencies so ``answer_query`` can call
    it with only the query parameters."""
    sources_repo = SourceRepository(session)

    async def _run(
        *, allowed_kb_ids: tuple[UUID, ...], source_id: UUID, sql: str, row_limit: int
    ) -> QueryDatabaseOutput:
        return await query_database(
            QueryDatabaseInput(
                allowed_kb_ids=allowed_kb_ids,
                source_id=source_id,
                sql=sql,
                row_limit=row_limit,
            ),
            sources_repo=sources_repo,
            connectors=DATABASE_CONNECTORS,
            encryptor=encryptor,
        )

    return _run


def build_answer_query_deps(
    session: AsyncSession,
    ctx: RequestContext,
    settings: Settings,
    qdrant: QdrantStore,
) -> dict[str, Any]:
    """Construct the repository + inference dependencies ``answer_query`` needs.

    Shared by the playground chat endpoint, the public-widget chat endpoint and
    the eval run/calibration jobs — the single source of truth for the
    ``answer_query`` dependency bundle.
    """
    encryptor = FernetSecretEncryptor(settings.fernet_key)
    return {
        "tenant_id": ctx.tenant_id,
        "chatbot_repo": ChatbotRepository(session, ctx),
        "kb_repo": KnowledgeBaseRepository(session, ctx),
        "sources_repo": SourceRepository(session),
        "credentials_repo": ProviderCredentialRepository(session, ctx),
        "session_repo": ChatSessionRepository(session, ctx),
        "message_repo": ChatMessageRepository(session),
        "llm_dispatcher": LLMDispatcher.default(),
        "embedder_dispatcher": EmbedderDispatcher.default(),
        "qdrant": qdrant,
        "encryptor": encryptor,
        "ollama_base_url": settings.ollama_base_url,
        "query_database_fn": make_query_database_fn(session, encryptor),
    }


# ---------------------------------------------------------------------------
# FastAPI Depends providers (request-scoped)
# ---------------------------------------------------------------------------


def get_encryptor(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> SecretEncryptor:
    return FernetSecretEncryptor(settings.fernet_key)


def get_storage(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> LocalStorage:
    return LocalStorage(root=settings.storage_local_path)


async def get_qdrant(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AsyncIterator[QdrantStore]:
    """Yield a QdrantStore and guarantee it is closed after the request."""
    store = QdrantStore(settings.qdrant_url, settings.qdrant_api_key)
    try:
        yield store
    finally:
        await store.close()


def get_chatbot_repo(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> ChatbotRepository:
    return ChatbotRepository(session, ctx)


def get_kb_repo(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session, ctx)


def get_sources_repo(
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> SourceRepository:
    return SourceRepository(session)


def get_credentials_repo(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> ProviderCredentialRepository:
    return ProviderCredentialRepository(session, ctx)


def get_eval_dataset_repo(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> EvalDatasetRepository:
    return EvalDatasetRepository(session, ctx)


def get_eval_dataset_item_repo(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> EvalDatasetItemRepository:
    return EvalDatasetItemRepository(session, ctx)


def get_eval_run_repo(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> EvalRunRepository:
    return EvalRunRepository(session, ctx)
