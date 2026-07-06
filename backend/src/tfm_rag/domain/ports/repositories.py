"""Repository ports — the persistence contracts `application/` depends on.

These Protocols speak DOMAIN language only: entities from `domain.entities`,
UUIDs and value objects. They never mention ORM `*Row` models nor
`AsyncSession` — those live behind the concrete adapters in
`infrastructure/persistence/repositories/`, which implement these ports by
mapping rows to entities (`_to_entity`).

Naming convention: `...RepositoryPort`. Concrete adapters keep their legacy
row-returning methods (consumed by not-yet-migrated modules) and ADD the
entity-returning methods declared here; the legacy methods are removed as
Tasks 7-9 migrate the remaining application modules. New repository ports for
those modules are appended to this file.
"""
from typing import Any, Protocol
from uuid import UUID

from tfm_rag.domain.entities.chat_message import ChatMessage, MessageRole
from tfm_rag.domain.entities.chat_session import ChatSession, SessionOrigin
from tfm_rag.domain.entities.chatbot import Chatbot
from tfm_rag.domain.entities.eval_dataset import (
    EvalDataset,
    EvalDatasetItem,
    EvalDatasetItemInput,
)
from tfm_rag.domain.entities.ingestion_job import IngestionJob
from tfm_rag.domain.entities.knowledge_base import KnowledgeBase
from tfm_rag.domain.entities.provider_credential import ProviderCredential
from tfm_rag.domain.entities.source import Source
from tfm_rag.domain.entities.user import User
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.model_ref import ModelRef
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.domain.value_objects.role_llm_selections import RoleLLMSelections
from tfm_rag.domain.value_objects.widget_config import WidgetConfig


class ChatbotRepositoryPort(Protocol):
    """Reads chatbots (tenant-scoped) as `Chatbot` aggregates."""

    async def get_chatbot(self, chatbot_id: UUID) -> Chatbot:
        """Return the chatbot (with its attached `kb_ids` populated).

        Raises `NotFoundError` if the chatbot does not exist in the tenant.
        """
        ...

    async def chatbot_exists(self, chatbot_id: UUID) -> bool:
        """Lightweight existence check, scoped to the tenant.

        Prefer this over `get_chatbot` when the caller only needs to
        validate existence (e.g. before creating/listing sessions) — it
        avoids parsing the chatbot's JSONB value objects and the extra
        kb-link query that `get_chatbot` does.
        """
        ...

    async def find_chatbot_by_name(self, name: str) -> Chatbot | None:
        """Return the tenant's chatbot with this exact name, or None."""
        ...

    async def list_chatbots(
        self, *, limit: int, offset: int
    ) -> list[Chatbot]:
        """Return the tenant's chatbots (paginated), each with kb_ids populated."""
        ...

    async def create_chatbot(
        self,
        *,
        name: str,
        description: str | None,
        system_prompt: str,
        llm_selection: LLMSelection,
        role_llm_selections: RoleLLMSelections,
        pipeline_config: PipelineConfig,
        widget_config: WidgetConfig,
        public_key: str,
        kb_ids: list[UUID],
    ) -> Chatbot:
        """Persist a new chatbot + its KB links (tenant from the adapter's
        context) and commit. Returns the persisted entity.
        """
        ...

    async def update_chatbot(
        self,
        chatbot_id: UUID,
        *,
        name: str,
        description: str | None,
        system_prompt: str,
        llm_selection: LLMSelection,
        role_llm_selections: RoleLLMSelections,
        pipeline_config: PipelineConfig,
        widget_config: WidgetConfig,
        kb_ids: list[UUID] | None,
    ) -> Chatbot:
        """Overwrite the chatbot's mutable scalar fields with these resolved
        values and commit. If `kb_ids` is not None, replaces the KB links;
        otherwise the current links are preserved. Raises NotFoundError if
        missing in the tenant.
        """
        ...

    async def delete_chatbot(self, chatbot_id: UUID) -> None:
        """Delete the chatbot (KB links cascade) and commit.

        Raises `ChatbotNotFoundError` if missing in the tenant.
        """
        ...


class KnowledgeBaseRepositoryPort(Protocol):
    """Reads/writes knowledge bases (tenant-scoped) as `KnowledgeBase`."""

    async def get_knowledge_base(self, kb_id: UUID) -> KnowledgeBase:
        """Return the KB. Raises `NotFoundError` if missing in the tenant."""
        ...

    async def find_by_name(self, name: str) -> KnowledgeBase | None:
        """Return the tenant's KB with this exact name, or None."""
        ...

    async def list_knowledge_bases(
        self, *, limit: int, offset: int
    ) -> list[KnowledgeBase]:
        """Return the tenant's knowledge bases (paginated)."""
        ...

    async def create_knowledge_base(
        self,
        *,
        name: str,
        description: str | None,
        chunking_config: ChunkingConfig,
        embedding_selection: EmbeddingSelection,
        description_llm: ModelRef | None,
    ) -> KnowledgeBase:
        """Persist a new KB (tenant from the adapter's context) and commit.

        Returns the persisted entity.
        """
        ...

    async def update_knowledge_base(
        self,
        kb_id: UUID,
        *,
        name: str,
        description: str | None,
        chunking_config: ChunkingConfig,
        embedding_selection: EmbeddingSelection,
        description_llm: ModelRef | None,
    ) -> KnowledgeBase:
        """Overwrite the KB's mutable fields with these resolved values and
        commit. Raises `NotFoundError` if missing in the tenant.
        """
        ...

    async def delete_knowledge_base(self, kb_id: UUID) -> None:
        """Delete the KB and commit.

        Raises `NotFoundError` if missing in the tenant, or
        `KnowledgeBaseInUseError` if a chatbot still references it (FK RESTRICT).
        The commit flushes any other pending work in the same unit of work.
        """
        ...


class SourceRepositoryPort(Protocol):
    """Reads/writes sources, scoped through their parent KB, as `Source`."""

    async def list_sources_by_kb(self, kb_id: UUID) -> list[Source]:
        """Return every source attached to `kb_id`."""
        ...

    async def get_source(self, kb_id: UUID, source_id: UUID) -> Source:
        """KB-scoped lookup. Raises `SourceNotFoundError` if missing."""
        ...

    async def get_source_unscoped(self, source_id: UUID) -> Source:
        """Tenant-agnostic lookup by source_id.

        UNSCOPED: does NOT verify tenant/KB ownership — callers MUST enforce
        it (e.g. checking `source.kb_id` against the current chatbot's KBs).
        Raises `SourceNotFoundError` if no such source exists.
        """
        ...

    async def insert_document_source(
        self,
        *,
        source_id: UUID,
        kb_id: UUID,
        storage_uri: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
    ) -> None:
        """Persist a new uploaded-document Source (ingest_status='not_started').

        Flushes but does NOT commit — the caller commits it together with the
        job row it schedules. The `source_id` is generated by the caller so it
        can name the storage object before the row exists.
        """
        ...

    async def insert_database_source(
        self, *, kb_id: UUID, payload: dict[str, Any]
    ) -> UUID:
        """Persist a new database Source (ingest_status='done') and commit.

        Returns the new source id.
        """
        ...

    async def delete_source(self, kb_id: UUID, source_id: UUID) -> None:
        """Remove the source row (KB-scoped) and commit, so external cleanup
        (Qdrant/storage) only runs against a durable delete. Raises
        `SourceNotFoundError` if it does not exist."""
        ...


class IngestionJobRepositoryPort(Protocol):
    """Reads/creates ingestion jobs (tenant-scoped) as `IngestionJob`."""

    async def get_ingestion_job(self, job_id: UUID) -> IngestionJob:
        """Return the job. Raises `NotFoundError` if missing in the tenant."""
        ...

    async def create_queued_job(self, *, source_id: UUID) -> UUID:
        """Persist a new queued job (progress=0) for `source_id` and return its
        id. Flushes but does NOT commit — the caller commits it together with
        the source row before scheduling the background runner."""
        ...


class IngestionJobStorePort(Protocol):
    """Background state machine for a running ingestion job.

    Each mutating method opens its own unit of work and commits, so a
    concurrent status poller observes progress transitions independently.
    Reads return domain entities (or None) rather than ORM rows.
    """

    async def load_job(self, job_id: UUID) -> IngestionJob | None:
        """Tenant-scoped read; None if the job was deleted / wrong tenant."""
        ...

    async def load_source(self, source_id: UUID) -> Source | None:
        """Unscoped read by source_id; None if the source is gone."""
        ...

    async def load_knowledge_base(self, kb_id: UUID) -> KnowledgeBase | None:
        """Tenant-scoped read; None if the KB was deleted."""
        ...

    async def mark_running(self, *, job_id: UUID, source_id: UUID) -> None:
        """Set job.status=running/progress=0 and source.ingest_status=running."""
        ...

    async def update_progress(
        self,
        *,
        job_id: UUID,
        progress: int,
        stage: str | None,
        items_done: int | None,
        items_total: int | None,
    ) -> None:
        """Persist a progress tick (job row only)."""
        ...

    async def mark_done(self, *, job_id: UUID, source_id: UUID) -> None:
        """Set job done (progress=100) and source done (last_ingest_at, error
        cleared)."""
        ...

    async def fail_job(self, *, job_id: UUID, error: str) -> None:
        """Mark only the job failed (used when its source/KB is gone)."""
        ...

    async def fail_job_and_source(
        self, *, job_id: UUID, source_id: UUID, error: str
    ) -> None:
        """Mark both the job and its source failed."""
        ...

    async def set_source_description(
        self, *, source_id: UUID, description: str
    ) -> None:
        """Persist the best-effort auto-generated source description."""
        ...


class ProviderCredentialRepositoryPort(Protocol):
    """Reads provider credentials (tenant-scoped) as `ProviderCredential`."""

    async def get_credential(self, credential_id: UUID) -> ProviderCredential:
        """Return the credential. Raises `NotFoundError` if missing in tenant."""
        ...

    async def list_credentials(
        self, *, limit: int, offset: int
    ) -> list[ProviderCredential]:
        """Return the tenant's credentials (paginated)."""
        ...

    async def find_by_provider_and_label(
        self, provider_id: str, label: str
    ) -> ProviderCredential | None:
        """Return the tenant's credential with this exact (provider_id, label),
        or None."""
        ...

    async def create_credential(
        self,
        *,
        provider_id: str,
        label: str,
        api_key_encrypted: bytes,
        base_url: str | None,
        max_concurrency: int | None,
        min_request_interval_seconds: float | None,
    ) -> ProviderCredential:
        """Persist a new TENANT_CREDENTIAL-sourced credential and commit."""
        ...

    async def update_credential(
        self,
        credential_id: UUID,
        *,
        api_key_encrypted: bytes,
        base_url: str | None,
        max_concurrency: int | None,
        min_request_interval_seconds: float | None,
    ) -> ProviderCredential:
        """Overwrite the credential's mutable fields and commit.

        Raises `NotFoundError` if missing in the tenant.
        """
        ...

    async def delete_credential(self, credential_id: UUID) -> None:
        """Delete the credential and commit. Raises `NotFoundError` if missing."""
        ...


class EvalDatasetRepositoryPort(Protocol):
    """Reads/writes evaluation datasets (tenant-scoped) as `EvalDataset`."""

    async def get_dataset(self, dataset_id: UUID) -> EvalDataset:
        """Return the dataset. Raises `NotFoundError` if missing in the tenant."""
        ...

    async def find_dataset_by_name(self, name: str) -> EvalDataset | None:
        """Return the tenant's dataset with this exact name, or None."""
        ...

    async def list_datasets(self, *, limit: int) -> list[EvalDataset]:
        """Return the tenant's datasets (paginated)."""
        ...

    async def create_dataset(
        self,
        *,
        name: str,
        description: str | None,
        knowledge_base_id: UUID | None,
    ) -> EvalDataset:
        """Persist a new draft dataset (tenant from the adapter's context) and
        commit. Returns the persisted entity."""
        ...

    async def delete_dataset(self, dataset_id: UUID) -> None:
        """Stage the dataset-row DELETE (flush-only, NO commit) so it commits
        atomically with the caller's other pending work (e.g. the KB delete
        that follows). Raises `NotFoundError` if missing in the tenant."""
        ...

    async def set_sql_seed_artifact(
        self, dataset_id: UUID, *, uri: str
    ) -> EvalDataset:
        """Store the seed artifact URI and commit. Returns the updated entity.
        Raises `NotFoundError` if missing in the tenant."""
        ...

    async def set_processing(self, dataset_id: UUID) -> None:
        """Transition the dataset to status='processing' (error cleared) and
        commit. Raises `NotFoundError` if missing in the tenant."""
        ...

    async def set_ready(
        self, dataset_id: UUID, *, db_schema_name: str | None
    ) -> EvalDataset:
        """Transition the dataset to status='ready' (error cleared) and commit.
        `db_schema_name`, when not None, is stored (a provisioned SQL schema);
        None leaves the existing value untouched. Returns the updated entity."""
        ...

    async def set_failed(self, dataset_id: UUID, *, error: str) -> None:
        """Transition the dataset to status='failed' with `error` and commit.
        Raises `NotFoundError` if missing in the tenant."""
        ...


class EvalDatasetItemRepositoryPort(Protocol):
    """Reads/writes evaluation dataset rows (tenant-scoped) as
    `EvalDatasetItem`."""

    async def count_for_dataset(self, dataset_id: UUID) -> int:
        """Return the number of rows in the dataset."""
        ...

    async def list_items_by_dataset(
        self, dataset_id: UUID
    ) -> list[EvalDatasetItem]:
        """Return the dataset's rows ordered by ordinal."""
        ...

    async def replace_dataset_rows(
        self, dataset_id: UUID, items: list[EvalDatasetItemInput]
    ) -> None:
        """Delete the dataset's existing rows and insert `items` (ordinal
        assigned by insertion order), then commit atomically."""
        ...


class ChatSessionRepositoryPort(Protocol):
    """Reads/writes chat sessions (tenant-scoped) as `ChatSession` entities."""

    async def get_chat_session(self, session_id: UUID) -> ChatSession:
        """Return the session. Raises `NotFoundError` if missing in tenant."""
        ...

    async def create_chat_session(
        self,
        *,
        chatbot_id: UUID,
        origin: SessionOrigin,
        public_session_cookie: str | None,
    ) -> UUID:
        """Persist a new session (tenant taken from the adapter's context).

        Returns the new session id.
        """
        ...

    async def list_chat_sessions_by_chatbot(
        self, *, chatbot_id: UUID, limit: int, offset: int
    ) -> list[ChatSession]:
        """Return the chatbot's sessions, most-recently-active first."""
        ...

    async def touch(self, session_id: UUID) -> None:
        """Bump `last_activity_at`; no-op if the session isn't in the tenant."""
        ...


class ChatMessageRepositoryPort(Protocol):
    """Reads/writes chat messages (scoped through their parent session)."""

    async def list_messages_by_session(
        self, session_id: UUID
    ) -> list[ChatMessage]:
        """Return the session's messages in chronological order."""
        ...

    async def append_message(
        self,
        *,
        session_id: UUID,
        role: MessageRole,
        content: str,
        citations: list[dict[str, Any]] | None,
        metadata: dict[str, Any] | None,
    ) -> ChatMessage:
        """Append a message turn and return the persisted entity."""
        ...


class UserRepositoryPort(Protocol):
    """Reads/writes users for the UNAUTHENTICATED auth flows (login,
    register, Google OAuth) as `User` entities.

    Deliberately NOT tenant-scoped: email/google_sub lookups happen before
    any tenant context exists (the user's tenant is derived from the row).

    Commit contract: the write methods FLUSH but do NOT commit — the auth
    request's session dependency (`get_session`) commits the whole
    user+tenant+default-credential unit of work atomically at request end
    (and rolls back on exception). This mirrors the pre-port behaviour
    exactly; adding a commit here would change the auth flows' atomicity.
    """

    async def find_user_by_email(self, email: str) -> User | None:
        """Return the user with this email, or None."""
        ...

    async def find_user_by_google_sub(self, google_sub: str) -> User | None:
        """Return the user linked to this Google subject id, or None."""
        ...

    async def create_user(
        self,
        *,
        user_id: UUID,
        email: str,
        password_hash: str | None,
        google_sub: str | None,
        tenant_id: UUID,
    ) -> None:
        """Persist a new user. Flushes but does NOT commit (see class doc).

        `user_id` is generated by the caller so the JWT/result can carry it
        without re-reading the row.
        """
        ...

    async def link_google_sub(self, user_id: UUID, google_sub: str) -> None:
        """Set `google_sub` on an existing (password-registered) user.

        Flushes but does NOT commit (see class doc).
        """
        ...


class TenantRepositoryPort(Protocol):
    """Provisions tenants during signup (no tenant context exists yet).

    Commit contract: both methods FLUSH but do NOT commit — bootstrap runs
    inside the register/Google-login request, whose `get_session` dependency
    commits user+tenant+credential atomically at request end (rollback on
    exception). `create_tenant` MUST flush before returning so the default
    credential's FK to tenants.id resolves when it is inserted next.
    """

    async def create_tenant(
        self,
        *,
        tenant_id: UUID,
        name: str,
        qdrant_collection_prefix: str,
        storage_prefix: str,
    ) -> None:
        """Persist a new tenant row and flush (no commit — see class doc)."""
        ...

    async def add_default_ollama_credential(self, *, tenant_id: UUID) -> None:
        """Persist the fresh tenant's default Ollama provider credential.

        SERVER_ENV-sourced: no real API key is stored (a sentinel satisfies
        the NOT NULL column) and base_url stays NULL — the adapter reads
        `OLLAMA_BASE_URL` from Settings at call time. Flushes, no commit.
        """
        ...
