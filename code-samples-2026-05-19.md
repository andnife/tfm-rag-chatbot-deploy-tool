# Code samples — sesión de brainstorming 2026-05-19

Snippets Python literales generados durante la sesión. Acompañan al
`conversation-2026-05-19.log` (decisiones y rationale) y al `handover.md`
(estado y continuación). Aquí está SOLO el código, sin prosa.

> ⚠️ **AVISO — Este archivo es un snapshot de la sesión 1 (2026-05-19).**
> En la sesión 2 (cierre de §6) se introdujeron cambios estructurales
> que dejan parcialmente desactualizado este código. **No regenerar
> implementaciones desde aquí sin contrastar con el log y el handover.**
>
> Cambios clave que afectan a lo que aparece más abajo:
> - `KnowledgeSource` se sustituye por `KnowledgeBase` (contenedor a
>   nivel tenant) + `Source` polimórfico (`DocumentSource`,
>   `DatabaseSource`).
> - El `Chatbot` deja de "owns sources"; ahora referencia KBs en una
>   relación N:M (`chatbot_knowledge_base`).
> - `chunking_config` y `embedding_selection` migran del `Chatbot` a la
>   `KnowledgeBase` (config de indexación vive con la KB).
> - `PipelineConfig` se amplía con: `max_retrieval_iterations`,
>   `agentic_mode`, `enable_reranker`, `reranker_initial_top_k`,
>   `abstain_when_insufficient`, `router_llm_selection`.
> - Nuevo puerto `Reranker` (no presente en §5 abajo).
> - Nuevo VO `RetrievalIteration` (telemetría por iteración del loop
>   agéntico).
> - `Router` mantiene la firma pero su menú de tools se amplía a
>   `search_docs`, `query_database`, `final_answer`, `abstain`.
>
> El log (sección "SECCIÓN 6 — CASOS DE USO / SERVICIOS DE APLICACIÓN")
> tiene el modelo final de dominio canónico.

Estado al cierre de sesión 1: secciones 4 (dominio) y 5 (adaptadores)
presentadas. Sección 4 aprobada y cerrada. Sección 5 pendiente de las
preguntas Q5.1/Q5.2/Q5.3 (resueltas en sesión 2; ver log).

Todo el código asume Python 3.11+. Las entidades de dominio son
inmutables (`frozen=True`).

---

## 1. Entidades de dominio (`domain/entities/`)

### 1.1 User

```python
# domain/entities/user.py
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

@dataclass(frozen=True)
class User:
    id: UUID
    email: str
    password_hash: str | None              # None si el user sólo entra por OAuth
    full_name: str | None
    google_subject: str | None             # 'sub' del id_token de Google, único
    created_at: datetime
    last_login_at: datetime | None
```

### 1.2 Tenant

```python
# domain/entities/tenant.py
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

@dataclass(frozen=True)
class Tenant:
    id: UUID
    name: str                              # editable por el owner
    owner_user_id: UUID                    # 1:1 en MVP (1 admin = 1 tenant)
    qdrant_namespace: str                  # p.ej. f"tenant_{id.hex}"
    storage_prefix: str                    # p.ej. f"tenant_{id.hex}/"
    created_at: datetime
```

### 1.3 Chatbot (versión final con `LLMSelection`)

```python
# domain/entities/chatbot.py
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from domain.value_objects.pipeline_config import PipelineConfig
from domain.value_objects.selections import LLMSelection, EmbeddingSelection

class ChatbotStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"

class RouterMode(str, Enum):
    AUTO = "auto"
    DOCS_ONLY = "docs_only"
    SQL_ONLY = "sql_only"

@dataclass(frozen=True)
class Chatbot:
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    status: ChatbotStatus
    system_prompt: str                     # textarea libre
    default_language: str                  # 'es' | 'en'
    llm: LLMSelection                      # ver value_objects/selections.py
    embeddings: EmbeddingSelection
    router_llm: LLMSelection | None        # opcional; si None usa `llm`
    pipeline_config: PipelineConfig
    router_mode: RouterMode
    allowed_origins: list[str]             # CORS para widget público
    created_at: datetime
    updated_at: datetime
```

### 1.4 KnowledgeSource

```python
# domain/entities/knowledge_source.py
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

class KnowledgeSourceType(str, Enum):
    LOCAL_FILES = "local_files"
    CLOUD_STORAGE = "cloud_storage"
    SQL_DATABASE = "sql_database"

class KnowledgeSourceStatus(str, Enum):
    PENDING = "pending"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"
    STALE = "stale"                        # cambió config de chunking/embeddings

@dataclass(frozen=True)
class KnowledgeSource:
    id: UUID
    chatbot_id: UUID
    tenant_id: UUID                        # denormalizado para scoping rápido
    type: KnowledgeSourceType
    name: str                              # p.ej. 'Manual de producto v3'
    status: KnowledgeSourceStatus
    config: dict                           # payload por tipo, ver 1.4.1
    last_error: str | None
    chunks_count: int                      # se llena tras ingestión
    last_indexed_at: datetime | None
    created_at: datetime
```

#### 1.4.1 Payload de `KnowledgeSource.config` por tipo

```python
# LOCAL_FILES
{
    "files": [
        {"path": "tenant_xxx/file1.pdf", "size": 12345, "mime": "application/pdf"},
        # ...
    ]
}

# CLOUD_STORAGE
{
    "connector": "gdrive" | "s3" | "dropbox",
    "credential_ref": "<uuid de ProviderCredential>",
    "folder_id_or_prefix": "...",
    "include_subfolders": True
}

# SQL_DATABASE
{
    "engine": "postgres" | "mysql",
    "host": "...",
    "port": 5432,
    "database": "...",
    "schema": "public",
    "username": "readonly_user",
    "password_encrypted": "<bytes>",
    "tables": [
        {
            "name": "products",
            "description": "Catálogo...",
            "columns": [{"name": "price", "description": "Precio en EUR"}],
        }
    ],
}
```

### 1.5 IngestionJob

```python
# domain/entities/ingestion_job.py
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

class IngestionJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

@dataclass(frozen=True)
class IngestionJob:
    id: UUID
    tenant_id: UUID
    chatbot_id: UUID
    source_id: UUID
    status: IngestionJobStatus
    progress_pct: int                      # 0..100
    current_step: str | None               # 'loading' | 'chunking' | 'embedding' | 'storing'
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
```

### 1.6 ChatSession y ChatMessage

```python
# domain/entities/chat_session.py
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from domain.value_objects.citation import Citation
from domain.value_objects.route_decision import RouteDecision

@dataclass(frozen=True)
class ChatSession:
    id: UUID
    tenant_id: UUID
    chatbot_id: UUID
    external_session_id: str               # el session_id que envía el widget
    user_agent: str | None
    ip_hash: str | None                    # hash, no IP en claro
    created_at: datetime
    last_activity_at: datetime

class ChatRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"

@dataclass(frozen=True)
class ChatMessage:
    id: UUID
    session_id: UUID
    role: ChatRole
    content: str
    citations: list[Citation] | None       # solo en assistant
    route_decision: RouteDecision | None   # solo en assistant
    latency_ms: int | None                 # solo en assistant
    tokens_in: int | None
    tokens_out: int | None
    created_at: datetime
```

### 1.7 WidgetConfig

```python
# domain/entities/widget_config.py
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

class WidgetPosition(str, Enum):
    BOTTOM_RIGHT = "bottom-right"
    BOTTOM_LEFT = "bottom-left"

@dataclass(frozen=True)
class WidgetConfig:
    chatbot_id: UUID
    primary_color: str                     # hex '#1a73e8'
    bg_color: str
    text_color: str
    position: WidgetPosition
    title: str
    welcome_message: str
    avatar_url: str | None
    width_px: int                          # default 360
    height_px: int                         # default 560
    show_branding: bool                    # 'Powered by ...'
    updated_at: datetime
```

### 1.8 PromptTemplate

```python
# domain/entities/prompt_template.py
from dataclasses import dataclass

@dataclass(frozen=True)
class PromptTemplate:
    id: str                                # 'customer_support_formal'
    name: str                              # mostrado en UI
    description: str
    template: str                          # texto que rellena el textarea
```

### 1.9 ProviderCredential

```python
# domain/entities/provider_credential.py
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

@dataclass(frozen=True)
class ProviderCredential:
    id: UUID
    tenant_id: UUID
    provider_id: str                       # FK lógica al catálogo
    label: str                             # 'OpenAI personal'
    api_key_encrypted: bytes               # Fernet
    base_url: str | None                   # obligatorio si descriptor.requires_base_url_input
    extra: dict                            # por si un provider concreto necesita más campos
    created_at: datetime
```

---

## 2. Value objects (`domain/value_objects/`)

### 2.1 ChunkingConfig

```python
# domain/value_objects/chunking_config.py
from dataclasses import dataclass
from enum import Enum

class ChunkingStrategy(str, Enum):
    FIXED_SIZE = "fixed_size"
    BY_STRUCTURE = "by_structure"
    SEMANTIC = "semantic"

@dataclass(frozen=True)
class ChunkingConfig:
    strategy: ChunkingStrategy
    chunk_size: int                        # tokens (estimados) o chars según strategy
    chunk_overlap: int
```

### 2.2 PipelineConfig

```python
# domain/value_objects/pipeline_config.py
from dataclasses import dataclass
from enum import Enum

from domain.value_objects.chunking_config import ChunkingConfig

class PresetMode(str, Enum):
    SIMPLE = "simple"
    ADVANCED = "advanced"

class ContentTypeHint(str, Enum):
    SHORT_DOCS = "short_docs"
    LONG_DOCS = "long_docs"
    MIXED = "mixed"

@dataclass(frozen=True)
class PipelineConfig:
    mode: PresetMode
    content_hint: ContentTypeHint | None   # sólo si mode=SIMPLE
    chunking: ChunkingConfig
    top_k: int
    similarity_threshold: float            # 0..1
    max_history_turns: int                 # cuántos turnos pasados pasar al LLM
    max_context_tokens: int                # presupuesto de contexto
```

### 2.3 GenerationConfig

```python
# domain/value_objects/generation_config.py
from dataclasses import dataclass

@dataclass(frozen=True)
class GenerationConfig:
    temperature: float
    max_tokens: int
    top_p: float | None
    stop: list[str] | None
```

### 2.4 RouteDecision

```python
# domain/value_objects/route_decision.py
from dataclasses import dataclass
from enum import Enum

class ToolName(str, Enum):
    SEARCH_DOCS = "search_docs"
    QUERY_SQL = "query_sql"

@dataclass(frozen=True)
class RouteDecision:
    tools: list[ToolName]                  # 1+ herramientas a ejecutar
    rationale: str                         # explicación del router (logs)
    raw_response: dict                     # respuesta cruda del LLM router
```

### 2.5 Chunk / RetrievedChunk

```python
# domain/value_objects/chunk.py
from dataclasses import dataclass
from uuid import UUID

@dataclass(frozen=True)
class Chunk:
    text: str
    metadata: dict                         # source_id, source_name, page, section, char_start, char_end, ...

@dataclass(frozen=True)
class RetrievedChunk:
    chunk: Chunk
    score: float
    source_id: UUID
```

### 2.6 Citation (versión revisada, SIN snippet de texto)

```python
# domain/value_objects/citation.py
from dataclasses import dataclass
from uuid import UUID

@dataclass(frozen=True)
class Citation:
    source_id: UUID
    source_name: str          # denormalizado al momento de la cita
    location: str | None      # 'p.12' | 'sección 3.2' | 'tabla products, filas 1-7'
    chunk_id: str | None      # id del punto en Qdrant; resuelve el texto bajo demanda
    score: float | None       # similitud que tuvo en el momento de recuperarse
    # ─── NO hay campo `snippet` con el texto literal ───
```

### 2.7 LLMSelection / EmbeddingSelection

```python
# domain/value_objects/selections.py
from dataclasses import dataclass
from uuid import UUID

@dataclass(frozen=True)
class LLMSelection:
    provider_id: str                     # 'ollama' | 'openai' | 'openai_compat'
    credential_id: UUID | None           # None si descriptor.config_source == SERVER_ENV
    model_id: str                        # 'llama3.1:8b' | 'gpt-4o-mini' | ...

@dataclass(frozen=True)
class EmbeddingSelection:
    provider_id: str
    credential_id: UUID | None
    model_id: str
```

---

## 3. Puertos (`domain/ports/`)

### 3.1 LLMProvider

```python
# domain/ports/llm_provider.py
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

from domain.value_objects.generation_config import GenerationConfig

@dataclass(frozen=True)
class LLMMessage:
    role: str                              # 'system' | 'user' | 'assistant' | 'tool'
    content: str
    tool_calls: list[dict] | None = None   # formato OpenAI tool_calls
    tool_call_id: str | None = None        # para mensajes role='tool'

@dataclass(frozen=True)
class LLMResponse:
    content: str
    tool_calls: list[dict] | None
    tokens_in: int
    tokens_out: int
    raw: dict                              # respuesta del proveedor (debug)

class LLMProvider(ABC):
    """Genera texto a partir de mensajes. Soporta tool/function calling."""
    provider_id: str

    @abstractmethod
    async def generate(
        self,
        messages: list[LLMMessage],
        model_id: str,
        config: GenerationConfig,
        tools: list[dict] | None = None,
    ) -> LLMResponse: ...

    @abstractmethod
    async def stream(
        self,
        messages: list[LLMMessage],
        model_id: str,
        config: GenerationConfig,
    ) -> AsyncIterator[str]: ...

    @abstractmethod
    async def list_models(self) -> list[str]: ...
    # Errores: LLMConnectionError, LLMTimeoutError, LLMRateLimitError, LLMBadRequestError
```

### 3.2 EmbeddingProvider

```python
# domain/ports/embedding_provider.py
from abc import ABC, abstractmethod

class EmbeddingProvider(ABC):
    provider_id: str

    @abstractmethod
    async def embed_text(self, text: str, model_id: str) -> list[float]: ...

    @abstractmethod
    async def embed_batch(self, texts: list[str], model_id: str) -> list[list[float]]: ...

    @abstractmethod
    def dimension(self, model_id: str) -> int: ...

    @abstractmethod
    async def list_models(self) -> list[str]: ...
    # Errores: EmbeddingConnectionError, EmbeddingDimensionMismatch
```

### 3.3 VectorStore

```python
# domain/ports/vector_store.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from domain.value_objects.chunk import RetrievedChunk

@dataclass(frozen=True)
class VectorRecord:
    id: str                                # uuid string
    vector: list[float]
    payload: dict                          # incluye tenant_id, chatbot_id, source_id, text, metadata

@dataclass(frozen=True)
class SearchFilter:
    tenant_id: UUID                        # OBLIGATORIO — scoping multi-tenant
    chatbot_id: UUID                       # OBLIGATORIO
    source_ids: list[UUID] | None = None

class VectorStore(ABC):
    @abstractmethod
    async def ensure_collection(self, tenant_id: UUID, dimension: int) -> None: ...

    @abstractmethod
    async def upsert(self, tenant_id: UUID, records: list[VectorRecord]) -> None: ...

    @abstractmethod
    async def search(
        self,
        query_vector: list[float],
        filter: SearchFilter,
        top_k: int,
        score_threshold: float | None = None,
    ) -> list[RetrievedChunk]: ...

    @abstractmethod
    async def delete_by_source(self, tenant_id: UUID, source_id: UUID) -> int: ...

    @abstractmethod
    async def delete_collection(self, tenant_id: UUID) -> None: ...
    # Errores: VectorStoreUnavailable, CollectionNotFound
```

### 3.4 DocumentLoader

```python
# domain/ports/document_loader.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True)
class LoadedDocument:
    text: str
    metadata: dict                         # page_count, title, headings, ...

class DocumentLoader(ABC):
    supported_extensions: tuple[str, ...]

    @abstractmethod
    async def load(self, file_path: str) -> list[LoadedDocument]:
        """Devuelve UN documento por archivo en MVP (futuro: split por sección).
        Errores: DocumentLoadError, UnsupportedFormatError.
        """
```

### 3.5 CloudStorageConnector

```python
# domain/ports/cloud_storage_connector.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from domain.entities.provider_credential import ProviderCredential

@dataclass(frozen=True)
class RemoteFile:
    remote_id: str
    name: str
    size: int
    mime_type: str
    modified_at: datetime

class CloudStorageConnector(ABC):
    provider_id: str                       # 'gdrive' | 's3' | 'dropbox'

    @abstractmethod
    async def list_folder(
        self,
        credential: ProviderCredential,
        folder_id_or_prefix: str,
        include_subfolders: bool,
    ) -> list[RemoteFile]: ...

    @abstractmethod
    async def download(
        self,
        credential: ProviderCredential,
        remote_id: str,
        destination_path: str,
    ) -> None: ...

    @abstractmethod
    async def test_credential(self, credential: ProviderCredential) -> bool: ...
    # Errores: CloudAuthError, CloudNotFoundError, CloudConnectionError
```

### 3.6 SQLDataSource

```python
# domain/ports/sql_data_source.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True)
class TableSchema:
    name: str
    columns: list[dict]                    # [{'name', 'type', 'nullable', 'description'}]
    description: str | None
    row_count_estimate: int | None

@dataclass(frozen=True)
class SQLResult:
    columns: list[str]
    rows: list[tuple]
    row_count: int
    execution_ms: int

class SQLDataSource(ABC):
    engine_id: str                         # 'postgres' | 'mysql'

    @abstractmethod
    async def test_connection(self, config: dict) -> bool: ...

    @abstractmethod
    async def introspect_schema(
        self, config: dict, tables: list[str] | None
    ) -> list[TableSchema]: ...

    @abstractmethod
    async def execute_readonly(
        self, config: dict, sql: str, timeout_s: int
    ) -> SQLResult: ...
    # Errores: SQLConnectionError, SQLPermissionError, SQLTimeoutError, SQLExecutionError
```

### 3.7 Chunker

```python
# domain/ports/chunker.py
from abc import ABC, abstractmethod

from domain.value_objects.chunk import Chunk
from domain.value_objects.chunking_config import ChunkingStrategy, ChunkingConfig

class Chunker(ABC):
    strategy_id: ChunkingStrategy

    @abstractmethod
    def chunk(self, text: str, config: ChunkingConfig, doc_metadata: dict) -> list[Chunk]: ...
```

### 3.8 Router

```python
# domain/ports/router.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

from domain.entities.chat_session import ChatMessage
from domain.ports.llm_provider import LLMProvider
from domain.value_objects.route_decision import RouteDecision, ToolName

@dataclass(frozen=True)
class AvailableTool:
    name: ToolName
    description: str                       # descripción para el LLM router
    enabled: bool

class Router(ABC):
    @abstractmethod
    async def route(
        self,
        query: str,
        history: list[ChatMessage],
        available_tools: list[AvailableTool],
        llm: LLMProvider,
        router_model_id: str,
    ) -> RouteDecision: ...
```

### 3.9 QueryGuard

```python
# domain/ports/query_guard.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

from domain.ports.llm_provider import LLMProvider
from domain.ports.sql_data_source import TableSchema

@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    layer_blocked: str | None              # 'ast' | 'semantic' | 'connection_privilege'
    reason: str | None
    sanitized_sql: str | None              # SQL final tras normalización si pasa

class QueryGuard(ABC):
    @abstractmethod
    async def validate(
        self,
        sql: str,
        schema: list[TableSchema],
        judge_llm: LLMProvider | None = None,
    ) -> GuardResult:
        """Aplica las capas de validación que el adaptador implemente.

        Tres capas previstas en MVP:
          1. Privilegio mínimo: garantizado fuera (en la conexión SQL).
          2. AST sqlglot: rechaza si la sentencia no es un SELECT puro
             (sin múltiples statements, sin DDL/DML, sin EXECUTE/CALL).
          3. Juez semántico (opcional): un LLM ligero revisa intención.
        """
```

### 3.10 OAuthVerifier

```python
# domain/ports/oauth_verifier.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True)
class OAuthUserInfo:
    subject: str                           # id único del proveedor ('sub' en Google)
    email: str
    email_verified: bool
    full_name: str | None
    picture_url: str | None

class OAuthVerifier(ABC):
    provider_id: str                       # 'google'

    @abstractmethod
    async def verify_token(self, id_token: str) -> OAuthUserInfo:
        """Valida firma, expiración y audiencia. Devuelve user info.
        Errores: OAuthInvalidToken, OAuthExpiredToken, OAuthWrongAudience.
        """
```

### 3.11 SecretEncryptor

```python
# domain/ports/secret_encryptor.py
from abc import ABC, abstractmethod

class SecretEncryptor(ABC):
    @abstractmethod
    def encrypt(self, plaintext: str) -> bytes: ...

    @abstractmethod
    def decrypt(self, ciphertext: bytes) -> str: ...
    # Errores: SecretDecryptError (cambio de clave, corrupción)
```

---

## 4. Jerarquía de errores de dominio (`domain/errors.py`)

```python
# domain/errors.py
class DomainError(Exception): ...

class TenantScopeViolation(DomainError): ...      # ALGO intentó cruzar tenants
class EntityNotFound(DomainError): ...
class InvalidStateTransition(DomainError): ...    # p.ej. activar un draft sin fuentes

class LLMError(DomainError): ...
class LLMConnectionError(LLMError): ...
class LLMTimeoutError(LLMError): ...
class LLMRateLimitError(LLMError): ...
class LLMBadRequestError(LLMError): ...

class EmbeddingError(DomainError): ...
class EmbeddingConnectionError(EmbeddingError): ...
class EmbeddingDimensionMismatch(EmbeddingError): ...

class VectorStoreError(DomainError): ...
class VectorStoreUnavailable(VectorStoreError): ...
class CollectionNotFound(VectorStoreError): ...

class DocumentLoadError(DomainError): ...
class UnsupportedFormatError(DocumentLoadError): ...

class CloudError(DomainError): ...
class CloudAuthError(CloudError): ...
class CloudNotFoundError(CloudError): ...
class CloudConnectionError(CloudError): ...

class SQLError(DomainError): ...
class SQLConnectionError(SQLError): ...
class SQLPermissionError(SQLError): ...
class SQLTimeoutError(SQLError): ...
class SQLExecutionError(SQLError): ...
class SQLGuardBlocked(SQLError): ...               # se bloqueó por QueryGuard

class OAuthError(DomainError): ...
class OAuthInvalidToken(OAuthError): ...
class OAuthExpiredToken(OAuthError): ...
class OAuthWrongAudience(OAuthError): ...

class SecretDecryptError(DomainError): ...
```

---

## 5. Catálogo de proveedores (`domain/catalog/`)

### 5.1 LLM provider catalog

```python
# domain/catalog/llm_providers.py
from dataclasses import dataclass
from enum import Enum

from domain.ports.llm_provider import LLMProvider

class ConfigSource(str, Enum):
    SERVER_ENV = "server_env"                # configurado en .env por sysadmin (Ollama)
    TENANT_CREDENTIAL = "tenant_credential"  # el tenant guarda api_key + opt base_url

@dataclass(frozen=True)
class LLMProviderDescriptor:
    id: str                                  # 'ollama' | 'openai' | 'openai_compat'
    display_name: str
    description: str
    config_source: ConfigSource
    requires_base_url_input: bool            # True solo para 'openai_compat'
    supports_tool_calling: bool
    default_models: list[str]                # catálogo curado mostrado en UI

# Import diferido o lazy resolution para evitar circular imports
# desde domain/catalog hacia adapters/.

LLM_PROVIDER_CATALOG: dict[str, tuple[LLMProviderDescriptor, type[LLMProvider]]] = {
    "ollama": (
        LLMProviderDescriptor(
            id="ollama",
            display_name="Ollama (local)",
            description="Modelos open-weights ejecutándose en el servidor.",
            config_source=ConfigSource.SERVER_ENV,
            requires_base_url_input=False,
            supports_tool_calling=True,
            default_models=["llama3.1:8b", "mistral:7b", "qwen2.5:7b", "gemma2:9b"],
        ),
        # OllamaLLMAdapter — referenciado por string en composition_root para evitar import circular
        "adapters.llm.ollama_adapter:OllamaLLMAdapter",
    ),
    "openai": (
        LLMProviderDescriptor(
            id="openai",
            display_name="OpenAI",
            description="API oficial de OpenAI. Requiere tu API key.",
            config_source=ConfigSource.TENANT_CREDENTIAL,
            requires_base_url_input=False,
            supports_tool_calling=True,
            default_models=["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"],
        ),
        "adapters.llm.openai_adapter:OpenAILLMAdapter",
    ),
    "openai_compat": (
        LLMProviderDescriptor(
            id="openai_compat",
            display_name="Endpoint OpenAI-compatible (genérico)",
            description=(
                "Para Groq, Together AI, GitHub Models, OpenRouter, "
                "DeepSeek y cualquier endpoint con API Chat Completions."
            ),
            config_source=ConfigSource.TENANT_CREDENTIAL,
            requires_base_url_input=True,
            supports_tool_calling=True,
            default_models=[],                # el admin teclea el model_id
        ),
        "adapters.llm.openai_compat_adapter:OpenAICompatLLMAdapter",
    ),
}
```

### 5.2 Embedding provider catalog (análogo)

```python
# domain/catalog/embedding_providers.py
from dataclasses import dataclass

from domain.catalog.llm_providers import ConfigSource
from domain.ports.embedding_provider import EmbeddingProvider

@dataclass(frozen=True)
class EmbeddingProviderDescriptor:
    id: str
    display_name: str
    description: str
    config_source: ConfigSource
    requires_base_url_input: bool
    default_models: list[str]
    # Tabla de dimensiones por model_id — necesaria para validar antes de ingestar
    dimensions: dict[str, int]

EMBEDDING_PROVIDER_CATALOG: dict[
    str, tuple[EmbeddingProviderDescriptor, str]   # (descriptor, "module:class")
] = {
    "ollama": (
        EmbeddingProviderDescriptor(
            id="ollama",
            display_name="Ollama (local)",
            description="Modelos de embeddings ejecutándose en el servidor.",
            config_source=ConfigSource.SERVER_ENV,
            requires_base_url_input=False,
            default_models=["bge-m3", "nomic-embed-text", "embeddinggemma:300m"],
            dimensions={"bge-m3": 1024, "nomic-embed-text": 768, "embeddinggemma:300m": 768},
        ),
        "adapters.embeddings.ollama_emb_adapter:OllamaEmbeddingAdapter",
    ),
    "openai": (
        EmbeddingProviderDescriptor(
            id="openai",
            display_name="OpenAI",
            description="API oficial de OpenAI para embeddings.",
            config_source=ConfigSource.TENANT_CREDENTIAL,
            requires_base_url_input=False,
            default_models=["text-embedding-3-small", "text-embedding-3-large"],
            dimensions={"text-embedding-3-small": 1536, "text-embedding-3-large": 3072},
        ),
        "adapters.embeddings.openai_compat_emb_adapter:OpenAICompatEmbeddingAdapter",
    ),
    "openai_compat": (
        EmbeddingProviderDescriptor(
            id="openai_compat",
            display_name="Endpoint OpenAI-compatible (embeddings)",
            description="Para proveedores de embeddings con API OpenAI-compatible.",
            config_source=ConfigSource.TENANT_CREDENTIAL,
            requires_base_url_input=True,
            default_models=[],
            dimensions={},  # el admin debe declararla al crear la credencial
        ),
        "adapters.embeddings.openai_compat_emb_adapter:OpenAICompatEmbeddingAdapter",
    ),
}
```

---

## 6. Composition root (`infrastructure/composition_root.py`)

```python
# infrastructure/composition_root.py
import importlib
from uuid import UUID

from domain.catalog.llm_providers import LLM_PROVIDER_CATALOG, ConfigSource
from domain.errors import EntityNotFound
from domain.ports.llm_provider import LLMProvider
from domain.value_objects.selections import LLMSelection
from infrastructure.persistence.repos import credentials_repo
from infrastructure.secrets import secret_encryptor
from infrastructure.settings import settings

def _import_class(path: str) -> type:
    """'adapters.llm.ollama_adapter:OllamaLLMAdapter' -> class object."""
    module_path, class_name = path.split(":")
    module = importlib.import_module(module_path)
    return getattr(module, class_name)

def resolve_llm(selection: LLMSelection, tenant_id: UUID) -> LLMProvider:
    descriptor, adapter_path = LLM_PROVIDER_CATALOG[selection.provider_id]
    adapter_class = _import_class(adapter_path)

    if descriptor.config_source == ConfigSource.SERVER_ENV:
        # Ollama: base_url del .env, sin credential
        return adapter_class(base_url=settings.OLLAMA_BASE_URL)

    # TENANT_CREDENTIAL: hay que cargar y descifrar la credential
    if selection.credential_id is None:
        raise EntityNotFound(
            f"Provider {selection.provider_id} requiere credential pero LLMSelection no tiene credential_id"
        )
    credential = credentials_repo.get(selection.credential_id, tenant_id=tenant_id)
    api_key = secret_encryptor.decrypt(credential.api_key_encrypted)

    if descriptor.requires_base_url_input:
        return adapter_class(base_url=credential.base_url, api_key=api_key)
    return adapter_class(api_key=api_key)

# Análogo: resolve_embedding(selection, tenant_id) -> EmbeddingProvider.
# Análogo simplificado: resolve_vector_store() -> QdrantVectorStore (singleton del .env).
```

---

## 7. Adaptadores concretos (`adapters/`)

### 7.1 OpenAICompatLLMAdapter

```python
# adapters/llm/openai_compat_adapter.py
import openai
from openai import AsyncOpenAI

from domain.ports.llm_provider import LLMProvider, LLMMessage, LLMResponse
from domain.value_objects.generation_config import GenerationConfig
from domain.errors import (
    LLMConnectionError,
    LLMTimeoutError,
    LLMRateLimitError,
    LLMBadRequestError,
)

class OpenAICompatLLMAdapter(LLMProvider):
    provider_id = "openai_compat"

    def __init__(self, base_url: str, api_key: str, timeout_s: float = 30.0):
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout_s)

    @staticmethod
    def _to_openai_msg(m: LLMMessage) -> dict:
        d = {"role": m.role, "content": m.content}
        if m.tool_calls is not None:
            d["tool_calls"] = m.tool_calls
        if m.tool_call_id is not None:
            d["tool_call_id"] = m.tool_call_id
        return d

    async def generate(
        self,
        messages: list[LLMMessage],
        model_id: str,
        config: GenerationConfig,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        try:
            resp = await self._client.chat.completions.create(
                model=model_id,
                messages=[self._to_openai_msg(m) for m in messages],
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                top_p=config.top_p,
                stop=config.stop,
                tools=tools,
            )
        except openai.APITimeoutError as e:
            raise LLMTimeoutError(str(e)) from e
        except openai.RateLimitError as e:
            raise LLMRateLimitError(str(e)) from e
        except openai.APIConnectionError as e:
            raise LLMConnectionError(str(e)) from e
        except openai.BadRequestError as e:
            raise LLMBadRequestError(str(e)) from e

        choice = resp.choices[0].message
        return LLMResponse(
            content=choice.content or "",
            tool_calls=[tc.model_dump() for tc in (choice.tool_calls or [])] or None,
            tokens_in=resp.usage.prompt_tokens,
            tokens_out=resp.usage.completion_tokens,
            raw=resp.model_dump(),
        )

    async def stream(self, messages, model_id, config):
        # Análogo a generate() pero con stream=True y yields de deltas.
        raise NotImplementedError

    async def list_models(self) -> list[str]:
        models = await self._client.models.list()
        return [m.id for m in models.data]
```

`OpenAILLMAdapter` es idéntico pero sin recibir `base_url` (lo deja al SDK que apunte a `api.openai.com`). `OllamaLLMAdapter` usa `httpx` directamente contra `/api/chat` de Ollama.

### 7.2 QdrantVectorStore

```python
# adapters/vector_store/qdrant_adapter.py
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    VectorParams, Distance, FieldCondition, MatchValue, MatchAny, Filter,
)

from domain.ports.vector_store import VectorStore, VectorRecord, SearchFilter
from domain.value_objects.chunk import Chunk, RetrievedChunk

class QdrantVectorStore(VectorStore):
    def __init__(self, url: str, api_key: str | None = None):
        self._client = AsyncQdrantClient(url=url, api_key=api_key)

    @staticmethod
    def _collection_name(tenant_id: UUID) -> str:
        return f"tenant_{tenant_id.hex}"

    async def ensure_collection(self, tenant_id: UUID, dimension: int) -> None:
        name = self._collection_name(tenant_id)
        if not await self._client.collection_exists(name):
            await self._client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
            )

    async def upsert(self, tenant_id: UUID, records: list[VectorRecord]) -> None:
        await self._client.upsert(
            collection_name=self._collection_name(tenant_id),
            points=[
                {"id": r.id, "vector": r.vector, "payload": r.payload}
                for r in records
            ],
        )

    async def search(
        self,
        query_vector: list[float],
        filter: SearchFilter,
        top_k: int,
        score_threshold: float | None = None,
    ) -> list[RetrievedChunk]:
        must = [
            FieldCondition(key="tenant_id", match=MatchValue(value=str(filter.tenant_id))),
            FieldCondition(key="chatbot_id", match=MatchValue(value=str(filter.chatbot_id))),
        ]
        if filter.source_ids:
            must.append(
                FieldCondition(
                    key="source_id",
                    match=MatchAny(any=[str(s) for s in filter.source_ids]),
                )
            )
        results = await self._client.search(
            collection_name=self._collection_name(filter.tenant_id),
            query_vector=query_vector,
            query_filter=Filter(must=must),
            limit=top_k,
            score_threshold=score_threshold,
        )
        out: list[RetrievedChunk] = []
        for r in results:
            payload = r.payload or {}
            out.append(
                RetrievedChunk(
                    chunk=Chunk(text=payload.get("text", ""), metadata=payload),
                    score=r.score,
                    source_id=UUID(payload["source_id"]),
                )
            )
        return out

    async def delete_by_source(self, tenant_id: UUID, source_id: UUID) -> int:
        result = await self._client.delete(
            collection_name=self._collection_name(tenant_id),
            points_selector=Filter(
                must=[FieldCondition(key="source_id", match=MatchValue(value=str(source_id)))]
            ),
        )
        return result.operation_id  # ajustar al return real de la librería

    async def delete_collection(self, tenant_id: UUID) -> None:
        await self._client.delete_collection(self._collection_name(tenant_id))
```

### 7.3 PostgresSQLDataSource (snippet ejecutar read-only)

```python
# adapters/sql_sources/postgres_adapter.py
import asyncio
import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from domain.ports.sql_data_source import SQLDataSource, SQLResult
from domain.errors import SQLPermissionError, SQLTimeoutError, SQLExecutionError

class PostgresSQLDataSource(SQLDataSource):
    engine_id = "postgres"

    @staticmethod
    def _build_url(config: dict) -> str:
        return (
            f"postgresql+asyncpg://{config['username']}:{config['password']}"
            f"@{config['host']}:{config['port']}/{config['database']}"
        )

    async def execute_readonly(self, config: dict, sql: str, timeout_s: int) -> SQLResult:
        engine = create_async_engine(self._build_url(config), pool_pre_ping=True)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SET TRANSACTION READ ONLY"))
                await conn.execute(text(f"SET statement_timeout = {timeout_s * 1000}"))
                result = await conn.execute(text(sql))
                rows = result.fetchall()
                return SQLResult(
                    columns=list(result.keys()),
                    rows=[tuple(r) for r in rows],
                    row_count=len(rows),
                    execution_ms=0,  # medir con time.monotonic en producción
                )
        except asyncpg.exceptions.InsufficientPrivilegeError as e:
            raise SQLPermissionError(str(e)) from e
        except asyncio.TimeoutError as e:
            raise SQLTimeoutError(str(e)) from e
        except Exception as e:
            raise SQLExecutionError(str(e)) from e
        finally:
            await engine.dispose()

    async def test_connection(self, config: dict) -> bool:
        # similar pero ejecuta SELECT 1 y retorna True/False
        raise NotImplementedError

    async def introspect_schema(self, config: dict, tables):
        # consulta information_schema y devuelve list[TableSchema]
        raise NotImplementedError
```

### 7.4 LLMFunctionCallingRouter

```python
# adapters/router/llm_function_calling_router.py
from domain.entities.chat_session import ChatMessage
from domain.ports.llm_provider import LLMProvider, LLMMessage
from domain.ports.router import Router, AvailableTool
from domain.value_objects.generation_config import GenerationConfig
from domain.value_objects.route_decision import RouteDecision, ToolName

class LLMFunctionCallingRouter(Router):
    @staticmethod
    def _tool_to_openai_schema(t: AvailableTool) -> dict:
        return {
            "type": "function",
            "function": {
                "name": t.name.value,
                "description": t.description,
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    @staticmethod
    def _build_router_prompt(query: str, history: list[ChatMessage], tools: list[AvailableTool]):
        system = (
            "Eres un router de consultas. Recibes una pregunta del usuario y debes "
            "decidir qué herramienta(s) llamar para resolverla. Si la pregunta "
            "necesita información de documentos, llama search_docs. Si necesita "
            "datos estructurados de BD, llama query_sql. Si necesita ambas, llama "
            "las dos. No respondas al usuario, sólo decide herramientas."
        )
        msgs = [LLMMessage(role="system", content=system)]
        for m in history[-3:]:
            msgs.append(LLMMessage(role=m.role.value, content=m.content))
        msgs.append(LLMMessage(role="user", content=query))
        return msgs

    async def route(self, query, history, available_tools, llm: LLMProvider, router_model_id):
        tools_schema = [self._tool_to_openai_schema(t) for t in available_tools if t.enabled]
        messages = self._build_router_prompt(query, history, available_tools)
        response = await llm.generate(
            messages=messages,
            model_id=router_model_id,
            config=GenerationConfig(temperature=0, max_tokens=200, top_p=None, stop=None),
            tools=tools_schema,
        )
        if response.tool_calls:
            chosen = [ToolName(tc["function"]["name"]) for tc in response.tool_calls]
            return RouteDecision(
                tools=chosen,
                rationale=response.content or "",
                raw_response=response.raw,
            )
        # Fallback: search_docs si está disponible
        fallback = [
            ToolName.SEARCH_DOCS
            for t in available_tools
            if t.name == ToolName.SEARCH_DOCS and t.enabled
        ]
        return RouteDecision(
            tools=fallback,
            rationale="fallback: no tool call from router LLM",
            raw_response=response.raw,
        )
```

### 7.5 LayeredQueryGuard

```python
# adapters/guards/layered_query_guard.py
import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel, ParseError

from domain.ports.query_guard import QueryGuard, GuardResult

class LayeredQueryGuard(QueryGuard):
    async def validate(self, sql, schema, judge_llm=None) -> GuardResult:
        # Capa 1: AST sqlglot — debe ser SELECT puro
        try:
            parsed = sqlglot.parse(sql, error_level=ErrorLevel.RAISE)
        except ParseError as e:
            return GuardResult(
                allowed=False,
                layer_blocked="ast",
                reason=f"parse error: {e}",
                sanitized_sql=None,
            )
        if len(parsed) != 1:
            return GuardResult(
                allowed=False,
                layer_blocked="ast",
                reason="múltiples sentencias",
                sanitized_sql=None,
            )
        stmt = parsed[0]
        if not isinstance(stmt, exp.Select):
            return GuardResult(
                allowed=False,
                layer_blocked="ast",
                reason=f"sentencia no-SELECT: {type(stmt).__name__}",
                sanitized_sql=None,
            )
        mutating = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create, exp.Command)
        if any(isinstance(n, mutating) for n in stmt.walk()):
            return GuardResult(
                allowed=False,
                layer_blocked="ast",
                reason="contiene sentencia mutativa anidada",
                sanitized_sql=None,
            )

        sanitized = stmt.sql()

        # Capa 2: juez semántico (opcional)
        if judge_llm is not None:
            verdict = await self._semantic_judge(sanitized, schema, judge_llm)
            if not verdict["allow"]:
                return GuardResult(
                    allowed=False,
                    layer_blocked="semantic",
                    reason=verdict["reason"],
                    sanitized_sql=None,
                )

        # Capa 3: privilegio mínimo — garantizado por la conexión read-only
        return GuardResult(
            allowed=True,
            sanitized_sql=sanitized,
            layer_blocked=None,
            reason=None,
        )

    async def _semantic_judge(self, sql: str, schema, judge_llm) -> dict:
        # Prompt corto pidiendo JSON {allow: bool, reason: str}.
        # Implementación elidida: usa judge_llm.generate con un system prompt
        # explicando el esquema y los criterios.
        raise NotImplementedError
```

### 7.6 FernetSecretEncryptor

```python
# adapters/secrets/fernet_encryptor.py
from cryptography.fernet import Fernet, InvalidToken

from domain.ports.secret_encryptor import SecretEncryptor
from domain.errors import SecretDecryptError

class FernetSecretEncryptor(SecretEncryptor):
    def __init__(self, key: bytes):
        self._f = Fernet(key)

    def encrypt(self, plaintext: str) -> bytes:
        return self._f.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            return self._f.decrypt(ciphertext).decode("utf-8")
        except InvalidToken as e:
            raise SecretDecryptError("clave rotada o ciphertext corrupto") from e
```

### 7.7 Registry de DocumentLoaders

```python
# adapters/document_loaders/registry.py
from domain.ports.document_loader import DocumentLoader

from adapters.document_loaders.pdf_loader import PDFDocumentLoader
from adapters.document_loaders.docx_loader import DOCXDocumentLoader
from adapters.document_loaders.txt_loader import TXTDocumentLoader
from adapters.document_loaders.csv_loader import CSVDocumentLoader
from adapters.document_loaders.markdown_loader import MarkdownDocumentLoader

DOCUMENT_LOADERS: dict[str, type[DocumentLoader]] = {
    ".pdf": PDFDocumentLoader,
    ".docx": DOCXDocumentLoader,
    ".txt": TXTDocumentLoader,
    ".csv": CSVDocumentLoader,
    ".md": MarkdownDocumentLoader,
    ".markdown": MarkdownDocumentLoader,
}
```

---

## 8. Tabla resumen de adaptadores MVP

| Puerto | Adaptadores MVP | Catálogo en código | Notas |
|---|---|---|---|
| `LLMProvider` | `OllamaLLMAdapter`, `OpenAILLMAdapter`, `OpenAICompatLLMAdapter` | Sí (`LLM_PROVIDER_CATALOG`) | Catálogo extensible vía nuevo adapter |
| `EmbeddingProvider` | `OllamaEmbeddingAdapter`, `OpenAICompatEmbeddingAdapter` | Sí (`EMBEDDING_PROVIDER_CATALOG`) | OpenAI cae sobre el compat con `base_url` fija |
| `VectorStore` | `QdrantVectorStore` | No (único) | Cambio a otro vendor sería refactor de runtime |
| `DocumentLoader` | `PDFDocumentLoader`, `DOCXDocumentLoader`, `TXTDocumentLoader`, `CSVDocumentLoader`, `MarkdownDocumentLoader` | Sí (`DOCUMENT_LOADERS`) | Añadir `.html`/`.xlsx`/`.json` futuro |
| `CloudStorageConnector` | `GoogleDriveConnector`, `S3Connector`, `DropboxConnector` | Sí (`CLOUD_STORAGE_CATALOG`) | Cada uno con su OAuth/keys |
| `SQLDataSource` | `PostgresSQLDataSource`, `MySQLSQLDataSource` | Sí (por engine) | SQLite/SQL Server futuros |
| `Chunker` | `FixedSizeChunker`, `StructureChunker`, `SemanticChunker` | Sí (por strategy) | Strategy del chatbot |
| `Router` | `LLMFunctionCallingRouter` | No | Futuro: heurístico, embedding-based |
| `QueryGuard` | `LayeredQueryGuard` | No | 3 capas: AST + juez LLM opcional + privilegio conexión |
| `OAuthVerifier` | `GoogleOAuthVerifier` | Sí (`OAUTH_VERIFIER_CATALOG`) | Futuro: GitHub, Microsoft |
| `SecretEncryptor` | `FernetSecretEncryptor` | No | Único |

---

## 9. Dependencias backend MVP

```
fastapi, uvicorn[standard]
pydantic, pydantic-settings
sqlalchemy[asyncio], alembic, asyncpg, aiomysql
qdrant-client
openai                              # cliente OpenAI + compat
httpx                               # Ollama nativo
pymupdf, python-docx, markdown-it-py
sqlglot                             # AST guard
cryptography                        # Fernet
google-auth                         # OAuth verify
google-api-python-client            # Drive
aioboto3                            # S3
dropbox                             # Dropbox SDK
ragas, datasets                     # evaluación
pytest, pytest-asyncio, pytest-cov  # tests
ruff, mypy                          # linting/typing
```

---

## 10. Reglas para los implementadores

1. **Inmutabilidad**: todas las entidades y VOs son `frozen=True`. Para mutar, los repositorios devuelven nuevas instancias.
2. **IDs**: siempre `UUID` (uuid4) generados en el dominio antes de persistir; nunca autoincrement de BD.
3. **Tenant scoping**: cualquier consulta al `VectorStore` que no incluya `tenant_id` en el filtro debe levantar `TenantScopeViolation`. Esto se prueba en tests dedicados.
4. **Async**: todos los puertos I/O-bound son `async`. Los chunkers son sync (CPU-bound).
5. **Tipos**: Python 3.11+, `str | None` (no `Optional[str]`).
6. **Mapper a SQLAlchemy**: vive en `infrastructure/persistence/mappers.py`, fuera del dominio. Convierte entidad ↔ modelo ORM en ambos sentidos.
7. **Resolución de adaptadores**: NUNCA hacer `from adapters... import ...` desde `domain/` o `application/`. El cableado es siempre vía `composition_root`.
8. **Errores del exterior**: los adaptadores capturan excepciones de librerías externas (`openai.APITimeoutError`, `asyncpg.exceptions.*`, etc.) y las re-lanzan como errores de dominio (`LLMTimeoutError`, `SQLPermissionError`, ...).

---

*Fin de los code samples preservados de la sesión 2026-05-19.*
