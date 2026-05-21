# CAP-CHATBOT-LIFECYCLE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Ship CRUD over `Chatbot` (single-POST wizard pattern from spec §3-E). After this plan, a tenant can `POST /api/chatbots` with `{name, system_prompt, llm_selection, kb_ids, pipeline_config, widget_config}` and the row persists + the N:M `chatbot_knowledge_base` rows are created. Cross-KB embedding compatibility is enforced (`IncompatibleEmbeddingsError`, 409). Deleting a KB referenced by a chatbot is blocked by the new RESTRICT FK and surfaces the `KnowledgeBaseInUseError` mapping that plan #7 already wired.

**Architecture:**
- New entity `Chatbot` + value objects `LLMSelection`, `PipelineConfig`, `GenerationConfig`. (`EmbeddingSelection` is reused from plan #7; `WidgetConfig` stays as a free-form JSONB dict here — its structured definition lands in plan #11 `CAP-CHATBOT-WIDGET-CONFIG`.)
- Two tables in migration 0006: `chatbots` (mirrors spec §9) + `chatbot_knowledge_base` (PK `(chatbot_id, kb_id)`, FKs `ON DELETE CASCADE` on chatbot_id and `ON DELETE RESTRICT` on kb_id — the latter is what makes plan #7's `IntegrityError → KnowledgeBaseInUseError` mapping actually fire).
- Five use cases in `application/chatbot_config/`: `CreateChatbot`, `UpdateChatbot`, `ListChatbots`, `GetChatbot`, `DeleteChatbot`. Patterns are identical to plan #7's KB use cases (Repo factories, View dataclasses, `_to_view`).
- API at `/api/chatbots/*`, mounted in `app.py`.

**Tech Stack:** No new deps beyond plans 1-8.

**Depends on:** plan #6 (catalog + provider credentials), plan #7 (KB entity + `EmbeddingSelection` VO + `IncompatibleEmbeddingsError` defined but unused).

**Out of scope (deferred):**
- `WidgetConfig` structured definition + `UpdateWidgetConfig`/`GetPublicWidgetConfig` use cases + dedicated route → plan #11 `CAP-CHATBOT-WIDGET-CONFIG`. Plan #10 stores `widget_config` as an opaque JSONB dict; the UI may put anything in it; plan #11 will introduce a strict pydantic model and migrate stored docs if needed.
- Chat runtime / agent loop / sessions / messages → plans #12, #14, #15.
- The `DELETE /api/chatbots/{id}` "cascade sessions + messages" wording in the spec is forward-looking — those tables don't exist yet (they come in plan #14). Plan #10 cascades only what exists today: the chatbot row + its `chatbot_knowledge_base` entries (the latter via `ON DELETE CASCADE` on chatbot_id).
- `PATCH /api/chatbots/{id}/widget-config` endpoint → plan #11.
- Any LLM-side validation of `llm_selection` (e.g. "does the model support tool calling?") is enforced lightly here (only that the provider/model is in the catalog); deeper checks happen at chat-time in plan #15.

---

## File structure

```
backend/src/tfm_rag/
├── domain/
│   ├── value_objects/
│   │   ├── llm_selection.py             # NEW
│   │   ├── pipeline_config.py           # NEW (+GenerationConfig inside)
│   │   └── (chunking_config.py, embedding_selection.py exist from plan #7)
│   ├── entities/
│   │   └── chatbot.py                   # NEW
│   └── errors/
│       └── chatbot.py                   # NEW (ChatbotNotFoundError; ChatbotAlreadyExistsError)
│
├── infrastructure/persistence/
│   ├── models/
│   │   ├── chatbots.py                  # NEW
│   │   └── chatbot_knowledge_base.py    # NEW (N:M)
│   └── repositories/
│       └── chatbots_repo.py             # NEW
│
└── application/
    └── chatbot_config/
        ├── __init__.py                  # NEW (empty)
        ├── create_chatbot.py            # NEW
        ├── update_chatbot.py            # NEW
        ├── list_chatbots.py             # NEW
        ├── get_chatbot.py               # NEW
        └── delete_chatbot.py            # NEW

backend/alembic/env.py                   # MODIFY: register chatbots + chatbot_knowledge_base
backend/alembic/versions/
└── 0006_chatbots_and_n2m.py             # NEW

backend/src/tfm_rag/infrastructure/api/
├── app.py                                # MODIFY: mount chatbots router
└── routers/
    └── chatbots.py                       # NEW

backend/tests/unit/
├── test_llm_selection.py                 # NEW
├── test_pipeline_config.py               # NEW
└── test_chatbot_use_cases.py             # NEW

backend/tests/integration/
└── test_chatbot_endpoints.py             # NEW
```

---

## Task 1 — Domain: VOs + entity + errors

**Files:**
- Create: `backend/src/tfm_rag/domain/value_objects/llm_selection.py`
- Create: `backend/src/tfm_rag/domain/value_objects/pipeline_config.py`
- Create: `backend/src/tfm_rag/domain/entities/chatbot.py`
- Create: `backend/src/tfm_rag/domain/errors/chatbot.py`
- Create: `backend/tests/unit/test_llm_selection.py`
- Create: `backend/tests/unit/test_pipeline_config.py`

- [ ] **Step 1.1: Create `backend/src/tfm_rag/domain/value_objects/llm_selection.py`**

```python
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from tfm_rag.domain.catalog.llm_providers import LLM_PROVIDER_CATALOG
from tfm_rag.domain.errors.common import ValidationError


@dataclass(frozen=True, slots=True)
class LLMSelection:
    """Pointer to a (provider, credential, model) tuple used to generate text.

    Symmetric to `EmbeddingSelection` from plan #7. Validates against
    `LLM_PROVIDER_CATALOG` only — deeper checks (does the model exist on the
    server, does the credential authenticate) happen at chat-runtime in
    plan #15.
    """

    provider_id: str
    credential_id: UUID
    model_id: str

    def __post_init__(self) -> None:
        descriptor = LLM_PROVIDER_CATALOG.get(self.provider_id)
        if descriptor is None:
            raise ValidationError(
                f"Unknown LLM provider: {self.provider_id!r}"
            )
        # Models inside the catalog are advisory (`default_models`). If the
        # tuple is empty (e.g. openai_compat) we accept any model_id.
        known = set(descriptor.default_models)
        if known and self.model_id not in known:
            raise ValidationError(
                f"Model {self.model_id!r} is not in the catalog for "
                f"provider {self.provider_id!r}. Known: {sorted(known)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "credential_id": str(self.credential_id),
            "model_id": self.model_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LLMSelection":
        return cls(
            provider_id=data["provider_id"],
            credential_id=UUID(str(data["credential_id"])),
            model_id=data["model_id"],
        )
```

- [ ] **Step 1.2: Create `backend/src/tfm_rag/domain/value_objects/pipeline_config.py`**

```python
from dataclasses import dataclass, field
from typing import Any

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.llm_selection import LLMSelection

# Bounds — match the spec §6 fiche.
TOP_K_MIN = 1
TOP_K_MAX = 50
SCORE_THRESHOLD_MIN = 0.0
SCORE_THRESHOLD_MAX = 1.0
MAX_RETRIEVAL_ITERATIONS_MIN = 1
MAX_RETRIEVAL_ITERATIONS_MAX = 5
RERANKER_INITIAL_TOP_K_MIN = 1
RERANKER_INITIAL_TOP_K_MAX = 200


@dataclass(frozen=True, slots=True)
class GenerationConfig:
    """LLM sampling knobs. Nested inside PipelineConfig under `generation`."""

    temperature: float = 0.2
    top_p: float = 1.0
    max_tokens: int = 1024

    def __post_init__(self) -> None:
        if not (0.0 <= self.temperature <= 2.0):
            raise ValidationError(
                f"temperature must be in [0, 2], got {self.temperature}"
            )
        if not (0.0 < self.top_p <= 1.0):
            raise ValidationError(
                f"top_p must be in (0, 1], got {self.top_p}"
            )
        if not (1 <= self.max_tokens <= 32_000):
            raise ValidationError(
                f"max_tokens must be in [1, 32000], got {self.max_tokens}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GenerationConfig":
        return cls(
            temperature=float(data.get("temperature", 0.2)),
            top_p=float(data.get("top_p", 1.0)),
            max_tokens=int(data.get("max_tokens", 1024)),
        )


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """Runtime config of a Chatbot's RAG pipeline.

    Lives at the Chatbot level (per spec §6 reparto-de-configuración table).
    Stored as a single JSONB blob in `chatbots.pipeline_config` plus the
    invariant CHECK at the SQL layer (`max_retrieval_iterations BETWEEN 1 AND 5`).
    """

    top_k: int = 5
    score_threshold: float = 0.0
    agentic_mode: bool = True
    max_retrieval_iterations: int = 3
    enable_reranker: bool = False
    reranker_initial_top_k: int = 30
    abstain_when_insufficient: bool = True
    router_llm_selection: LLMSelection | None = None
    generation: GenerationConfig = field(default_factory=GenerationConfig)

    def __post_init__(self) -> None:
        if not (TOP_K_MIN <= self.top_k <= TOP_K_MAX):
            raise ValidationError(
                f"top_k must be in [{TOP_K_MIN},{TOP_K_MAX}], got {self.top_k}"
            )
        if not (SCORE_THRESHOLD_MIN <= self.score_threshold <= SCORE_THRESHOLD_MAX):
            raise ValidationError(
                f"score_threshold must be in [0, 1], got {self.score_threshold}"
            )
        if not (
            MAX_RETRIEVAL_ITERATIONS_MIN
            <= self.max_retrieval_iterations
            <= MAX_RETRIEVAL_ITERATIONS_MAX
        ):
            raise ValidationError(
                "max_retrieval_iterations must be in "
                f"[{MAX_RETRIEVAL_ITERATIONS_MIN},{MAX_RETRIEVAL_ITERATIONS_MAX}], "
                f"got {self.max_retrieval_iterations}"
            )
        if self.enable_reranker and not (
            RERANKER_INITIAL_TOP_K_MIN
            <= self.reranker_initial_top_k
            <= RERANKER_INITIAL_TOP_K_MAX
        ):
            raise ValidationError(
                "reranker_initial_top_k must be in "
                f"[{RERANKER_INITIAL_TOP_K_MIN},{RERANKER_INITIAL_TOP_K_MAX}], "
                f"got {self.reranker_initial_top_k}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "top_k": self.top_k,
            "score_threshold": self.score_threshold,
            "agentic_mode": self.agentic_mode,
            "max_retrieval_iterations": self.max_retrieval_iterations,
            "enable_reranker": self.enable_reranker,
            "reranker_initial_top_k": self.reranker_initial_top_k,
            "abstain_when_insufficient": self.abstain_when_insufficient,
            "router_llm_selection": (
                self.router_llm_selection.to_dict()
                if self.router_llm_selection
                else None
            ),
            "generation": self.generation.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PipelineConfig":
        router = data.get("router_llm_selection")
        gen = data.get("generation") or {}
        return cls(
            top_k=int(data.get("top_k", 5)),
            score_threshold=float(data.get("score_threshold", 0.0)),
            agentic_mode=bool(data.get("agentic_mode", True)),
            max_retrieval_iterations=int(
                data.get("max_retrieval_iterations", 3)
            ),
            enable_reranker=bool(data.get("enable_reranker", False)),
            reranker_initial_top_k=int(data.get("reranker_initial_top_k", 30)),
            abstain_when_insufficient=bool(
                data.get("abstain_when_insufficient", True)
            ),
            router_llm_selection=(
                LLMSelection.from_dict(router) if router else None
            ),
            generation=GenerationConfig.from_dict(gen),
        )

    @classmethod
    def default(cls) -> "PipelineConfig":
        return cls()
```

- [ ] **Step 1.3: Create `backend/src/tfm_rag/domain/entities/chatbot.py`**

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig


@dataclass(frozen=True, slots=True)
class Chatbot:
    """Chatbot aggregate root.

    `widget_config` stays as `dict[str, Any]` in plan #10 — a structured VO
    arrives in plan #11 CAP-CHATBOT-WIDGET-CONFIG.

    `kb_ids` is the materialised N:M projection (read from
    chatbot_knowledge_base); the entity does NOT manage the link rows
    directly — that's the use case's job.
    """

    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    system_prompt: str
    llm_selection: LLMSelection
    pipeline_config: PipelineConfig
    widget_config: dict[str, Any]
    kb_ids: list[UUID]
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 1.4: Create `backend/src/tfm_rag/domain/errors/chatbot.py`**

```python
from tfm_rag.domain.errors.common import DomainError, NotFoundError


class ChatbotNotFoundError(NotFoundError):
    """Raised when a Chatbot does not exist in the tenant."""


class ChatbotAlreadyExistsError(DomainError):
    """Raised when a tenant already has a Chatbot with the requested name."""
```

- [ ] **Step 1.5: Write the failing unit tests for the VOs**

Create `backend/tests/unit/test_llm_selection.py`:

```python
from uuid import uuid4

import pytest

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.llm_selection import LLMSelection


def test_known_combo_accepted() -> None:
    s = LLMSelection(provider_id="ollama", credential_id=uuid4(), model_id="llama3.1")
    assert s.model_id == "llama3.1"


def test_unknown_provider_rejected() -> None:
    with pytest.raises(ValidationError, match="Unknown LLM provider"):
        LLMSelection(provider_id="not_a_provider", credential_id=uuid4(), model_id="x")


def test_unknown_model_rejected_when_catalog_lists_some() -> None:
    # ollama has a non-empty default_models tuple
    with pytest.raises(ValidationError, match="not in the catalog"):
        LLMSelection(provider_id="ollama", credential_id=uuid4(), model_id="phantom-model")


def test_openai_compat_accepts_any_model() -> None:
    # default_models=() for openai_compat → no model restriction
    s = LLMSelection(
        provider_id="openai_compat",
        credential_id=uuid4(),
        model_id="some-custom/model-7b",
    )
    assert s.model_id == "some-custom/model-7b"


def test_round_trip() -> None:
    cid = uuid4()
    s = LLMSelection(provider_id="ollama", credential_id=cid, model_id="llama3.1")
    assert LLMSelection.from_dict(s.to_dict()) == s
```

Create `backend/tests/unit/test_pipeline_config.py`:

```python
import pytest
from uuid import uuid4

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import (
    GenerationConfig,
    PipelineConfig,
)


def test_default_is_valid() -> None:
    p = PipelineConfig.default()
    assert p.top_k == 5
    assert p.max_retrieval_iterations == 3
    assert p.agentic_mode is True
    assert p.enable_reranker is False
    assert isinstance(p.generation, GenerationConfig)


def test_max_iterations_above_5_rejected() -> None:
    with pytest.raises(ValidationError, match="max_retrieval_iterations"):
        PipelineConfig(max_retrieval_iterations=6)


def test_max_iterations_zero_rejected() -> None:
    with pytest.raises(ValidationError, match="max_retrieval_iterations"):
        PipelineConfig(max_retrieval_iterations=0)


def test_top_k_zero_rejected() -> None:
    with pytest.raises(ValidationError, match="top_k"):
        PipelineConfig(top_k=0)


def test_score_threshold_above_1_rejected() -> None:
    with pytest.raises(ValidationError, match="score_threshold"):
        PipelineConfig(score_threshold=1.5)


def test_generation_temperature_above_2_rejected() -> None:
    with pytest.raises(ValidationError, match="temperature"):
        GenerationConfig(temperature=3.0)


def test_generation_max_tokens_zero_rejected() -> None:
    with pytest.raises(ValidationError, match="max_tokens"):
        GenerationConfig(max_tokens=0)


def test_round_trip_with_router_and_generation() -> None:
    router = LLMSelection(provider_id="ollama", credential_id=uuid4(), model_id="llama3.1")
    p = PipelineConfig(
        top_k=10,
        score_threshold=0.3,
        agentic_mode=False,
        max_retrieval_iterations=2,
        enable_reranker=True,
        reranker_initial_top_k=30,
        abstain_when_insufficient=False,
        router_llm_selection=router,
        generation=GenerationConfig(temperature=0.7, top_p=0.9, max_tokens=2048),
    )
    assert PipelineConfig.from_dict(p.to_dict()) == p


def test_round_trip_default() -> None:
    p = PipelineConfig.default()
    assert PipelineConfig.from_dict(p.to_dict()) == p
```

- [ ] **Step 1.6: Run the VO tests, confirm they pass**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
pytest tests/unit/test_llm_selection.py tests/unit/test_pipeline_config.py -v
```

Expected: **5 (LLM) + 9 (Pipeline) = 14 PASSED**.

- [ ] **Step 1.7: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/domain/value_objects/llm_selection.py backend/src/tfm_rag/domain/value_objects/pipeline_config.py backend/src/tfm_rag/domain/entities/chatbot.py backend/src/tfm_rag/domain/errors/chatbot.py backend/tests/unit/test_llm_selection.py backend/tests/unit/test_pipeline_config.py
git commit -m "feat(domain): Chatbot entity + LLMSelection/PipelineConfig/GenerationConfig VOs + errors"
```

---

## Task 2 — Persistence: chatbots + N:M ORM + migration 0006 + repo

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/persistence/models/chatbots.py`
- Create: `backend/src/tfm_rag/infrastructure/persistence/models/chatbot_knowledge_base.py`
- Create: `backend/alembic/versions/0006_chatbots_and_n2m.py`
- Modify: `backend/alembic/env.py` (register the two new modules)
- Create: `backend/src/tfm_rag/infrastructure/persistence/repositories/chatbots_repo.py`
- Create: `backend/tests/integration/test_chatbots_migration.py`

- [ ] **Step 2.1: Write the failing migration integration test**

Create `backend/tests/integration/test_chatbots_migration.py`:

```python
import asyncio
import subprocess

import pytest
from sqlalchemy import inspect

from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings


@pytest.mark.integration
async def test_migration_0006_creates_chatbots_and_n2m(settings: Settings) -> None:
    result = await asyncio.to_thread(
        subprocess.run,
        ["alembic", "upgrade", "head"],
        cwd=".",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    engine = build_engine(settings.postgres_url)
    build_session_factory(engine)
    async with engine.connect() as conn:
        tables = await conn.run_sync(
            lambda sc: inspect(sc).get_table_names()
        )
        assert "chatbots" in tables
        assert "chatbot_knowledge_base" in tables

        chatbot_cols = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("chatbots")}
        )
        assert {
            "id", "tenant_id", "name", "description",
            "system_prompt", "llm_selection", "router_llm_selection",
            "pipeline_config", "widget_config",
            "created_at", "updated_at",
        } <= chatbot_cols

        n2m_cols = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("chatbot_knowledge_base")}
        )
        assert {"chatbot_id", "kb_id"} <= n2m_cols
    await engine.dispose()
```

- [ ] **Step 2.2: Create `backend/src/tfm_rag/infrastructure/persistence/models/chatbots.py`**

```python
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from tfm_rag.infrastructure.persistence.base import Base


class ChatbotRow(Base):
    __tablename__ = "chatbots"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "name",
            name="uq_chatbots_tenant_name",
        ),
        # Spec §9: invariant on max_retrieval_iterations
        CheckConstraint(
            "((pipeline_config->>'max_retrieval_iterations')::int "
            "BETWEEN 1 AND 5)",
            name="ck_chatbots_max_retrieval_iterations",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    system_prompt: Mapped[str] = mapped_column(String(8000), nullable=False)
    llm_selection: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    router_llm_selection: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    pipeline_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    widget_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
```

- [ ] **Step 2.3: Create `backend/src/tfm_rag/infrastructure/persistence/models/chatbot_knowledge_base.py`**

```python
from uuid import UUID

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from tfm_rag.infrastructure.persistence.base import Base


class ChatbotKnowledgeBaseRow(Base):
    """N:M link between chatbots and knowledge_bases.

    FK on kb_id is `ON DELETE RESTRICT` — this is what makes plan #7's
    `DeleteKnowledgeBase` raise `KnowledgeBaseInUseError` once chatbots
    reference a KB. FK on chatbot_id is `ON DELETE CASCADE`.
    """

    __tablename__ = "chatbot_knowledge_base"

    chatbot_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
    )
    kb_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
    )
```

Note: the FKs are declared in the migration (Task 2.4), not on the ORM columns. SQLAlchemy treats the column types + the migration as the source of truth; the join-table ORM exists only so `Base.metadata.create_all()` (in unit tests) can roundtrip the schema.

- [ ] **Step 2.4: Create `backend/alembic/versions/0006_chatbots_and_n2m.py`**

```python
"""create chatbots and chatbot_knowledge_base tables

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-21 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chatbots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("system_prompt", sa.String(length=8000), nullable=False),
        sa.Column("llm_selection", postgresql.JSONB(), nullable=False),
        sa.Column("router_llm_selection", postgresql.JSONB(), nullable=True),
        sa.Column("pipeline_config", postgresql.JSONB(), nullable=False),
        sa.Column("widget_config", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "name", name="uq_chatbots_tenant_name"
        ),
        sa.CheckConstraint(
            "((pipeline_config->>'max_retrieval_iterations')::int "
            "BETWEEN 1 AND 5)",
            name="ck_chatbots_max_retrieval_iterations",
        ),
    )
    op.create_index("ix_chatbots_tenant_id", "chatbots", ["tenant_id"])

    op.create_table(
        "chatbot_knowledge_base",
        sa.Column(
            "chatbot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chatbots.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "kb_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_chatbot_knowledge_base_kb_id",
        "chatbot_knowledge_base",
        ["kb_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chatbot_knowledge_base_kb_id",
        table_name="chatbot_knowledge_base",
    )
    op.drop_table("chatbot_knowledge_base")
    op.drop_index("ix_chatbots_tenant_id", table_name="chatbots")
    op.drop_table("chatbots")
```

- [ ] **Step 2.5: Register the new models in `backend/alembic/env.py`**

The model-imports block at the top of `env.py` should end up like this (merge alphabetically with what's already there):

```python
from tfm_rag.infrastructure.persistence.models import (
    chatbot_knowledge_base,  # noqa: F401
    chatbots,  # noqa: F401
    ingestion_jobs,  # noqa: F401
    knowledge_bases,  # noqa: F401
    provider_credentials,  # noqa: F401
    sources,  # noqa: F401
    tenants,  # noqa: F401
    users,  # noqa: F401
)
```

- [ ] **Step 2.6: Create `backend/src/tfm_rag/infrastructure/persistence/repositories/chatbots_repo.py`**

```python
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from typing import Any

from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError
from tfm_rag.infrastructure.persistence.models.chatbot_knowledge_base import (
    ChatbotKnowledgeBaseRow,
)
from tfm_rag.infrastructure.persistence.models.chatbots import ChatbotRow
from tfm_rag.infrastructure.persistence.repository import BaseRepository


class ChatbotRepository(BaseRepository[ChatbotRow]):
    model = ChatbotRow

    async def find_by_name(self, name: str) -> ChatbotRow | None:
        stmt = select(ChatbotRow).where(
            ChatbotRow.tenant_id == self._ctx.tenant_id,
            ChatbotRow.name == name,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_kb_ids(self, chatbot_id: UUID) -> list[UUID]:
        stmt = select(ChatbotKnowledgeBaseRow.kb_id).where(
            ChatbotKnowledgeBaseRow.chatbot_id == chatbot_id,
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def replace_kb_links(
        self, chatbot_id: UUID, kb_ids: list[UUID]
    ) -> None:
        """Replace the set of KBs attached to a chatbot.

        Caller MUST have validated that all kb_ids belong to the tenant and
        share embedding_selection. We delete-all + insert-all rather than
        diff because the chatbot wizard sends the whole set anyway.
        """
        await self._session.execute(
            delete(ChatbotKnowledgeBaseRow).where(
                ChatbotKnowledgeBaseRow.chatbot_id == chatbot_id,
            )
        )
        for kb_id in kb_ids:
            self._session.add(
                ChatbotKnowledgeBaseRow(chatbot_id=chatbot_id, kb_id=kb_id)
            )
        await self._session.flush()

    async def attempt_delete_with_cascade(self, chatbot_id: UUID) -> None:
        """Delete a chatbot. The N:M rows cascade via FK ON DELETE CASCADE on
        chatbot_id. KB rows themselves are NOT touched.
        """
        stmt = delete(ChatbotRow).where(
            ChatbotRow.id == chatbot_id,
            ChatbotRow.tenant_id == self._ctx.tenant_id,
        )
        result: CursorResult[Any] = await self._session.execute(stmt)  # type: ignore[assignment]
        if result.rowcount == 0:
            # Defer to caller; the tenant-aware NotFoundError flow lives in
            # the use case to keep the repo storage-agnostic.
            raise KnowledgeBaseNotFoundError(
                # Sentinel: use case maps this to ChatbotNotFoundError. We
                # reuse the type so we don't import the domain error here
                # — the repo stays in infra and doesn't depend on chatbot
                # errors. Use case translates.
                f"Chatbot row not found: {chatbot_id}"
            )
```

Note for implementer: the `attempt_delete_with_cascade` raises `KnowledgeBaseNotFoundError` as a sentinel that the use case (`delete_chatbot`) translates to `ChatbotNotFoundError`. This avoids the repo importing `domain.errors.chatbot` (it doesn't depend on the chatbot domain — only on `knowledge` for the existing convention). If you prefer to use `NotFoundError` directly from `domain.errors.common`, replace the import and the raise — both shapes are acceptable.

- [ ] **Step 2.7: Reset DB and run the migration test**

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
pytest tests/integration/test_chatbots_migration.py -m integration -v
```

Expected: PASS.

- [ ] **Step 2.8: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/infrastructure/persistence/models/chatbots.py backend/src/tfm_rag/infrastructure/persistence/models/chatbot_knowledge_base.py backend/alembic/versions/0006_chatbots_and_n2m.py backend/alembic/env.py backend/src/tfm_rag/infrastructure/persistence/repositories/chatbots_repo.py backend/tests/integration/test_chatbots_migration.py
git commit -m "feat(infra): chatbots + chatbot_knowledge_base ORM + migration 0006 + ChatbotRepository"
```

---

## Task 3 — Application use cases (5 of them) with unit tests

**Files:**
- Create: `backend/src/tfm_rag/application/chatbot_config/__init__.py` (empty)
- Create: `backend/src/tfm_rag/application/chatbot_config/create_chatbot.py`
- Create: `backend/src/tfm_rag/application/chatbot_config/update_chatbot.py`
- Create: `backend/src/tfm_rag/application/chatbot_config/list_chatbots.py`
- Create: `backend/src/tfm_rag/application/chatbot_config/get_chatbot.py`
- Create: `backend/src/tfm_rag/application/chatbot_config/delete_chatbot.py`
- Create: `backend/tests/unit/test_chatbot_use_cases.py`

- [ ] **Step 3.1: Write the failing unit tests**

Create `backend/tests/unit/test_chatbot_use_cases.py`:

```python
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from tfm_rag.application.chatbot_config.create_chatbot import (
    create_chatbot,
)
from tfm_rag.application.chatbot_config.delete_chatbot import delete_chatbot
from tfm_rag.application.chatbot_config.list_chatbots import list_chatbots
from tfm_rag.application.chatbot_config.update_chatbot import update_chatbot
from tfm_rag.domain.errors.chatbot import (
    ChatbotAlreadyExistsError,
    ChatbotNotFoundError,
)
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import IncompatibleEmbeddingsError
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
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


def _selection_768(credential_id: UUID | None = None) -> EmbeddingSelection:
    return EmbeddingSelection(
        provider_id="ollama",
        credential_id=credential_id or uuid4(),
        model_id="nomic-embed-text",
        dim=768,
    )


def _llm() -> LLMSelection:
    return LLMSelection(
        provider_id="ollama", credential_id=uuid4(), model_id="llama3.1"
    )


def _kb_row(selection: EmbeddingSelection) -> MagicMock:
    row = MagicMock()
    row.id = uuid4()
    row.embedding_selection = selection.to_dict()
    return row


@pytest.mark.asyncio
async def test_create_chatbot_with_zero_kbs_is_allowed() -> None:
    """Spec Q6.10: chatbots with 0 KBs are valid (LLM puro)."""
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    ctx = _ctx()

    chatbot_repo = MagicMock()
    chatbot_repo.find_by_name = AsyncMock(return_value=None)
    chatbot_repo.add = AsyncMock(side_effect=lambda r: r)
    chatbot_repo.replace_kb_links = AsyncMock()

    kb_repo = MagicMock()
    kb_repo.get = AsyncMock()  # never called when kb_ids is empty

    result = await create_chatbot(
        session, ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: kb_repo,
        name="LLM-only bot",
        description=None,
        system_prompt="Be concise.",
        llm_selection=_llm(),
        kb_ids=[],
        pipeline_config=PipelineConfig.default(),
        widget_config={"theme": "light"},
    )

    assert result.kb_ids == []
    kb_repo.get.assert_not_called()
    chatbot_repo.replace_kb_links.assert_awaited_once_with(result.id, [])


@pytest.mark.asyncio
async def test_create_chatbot_with_compatible_kbs_succeeds() -> None:
    session = MagicMock()
    ctx = _ctx()
    selection = _selection_1024()
    kb1, kb2 = _kb_row(selection), _kb_row(selection)

    chatbot_repo = MagicMock()
    chatbot_repo.find_by_name = AsyncMock(return_value=None)
    chatbot_repo.add = AsyncMock(side_effect=lambda r: r)
    chatbot_repo.replace_kb_links = AsyncMock()

    kb_repo = MagicMock()
    kb_repo.get = AsyncMock(side_effect=[kb1, kb2])

    result = await create_chatbot(
        session, ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: kb_repo,
        name="Bot",
        description=None,
        system_prompt="Be concise.",
        llm_selection=_llm(),
        kb_ids=[kb1.id, kb2.id],
        pipeline_config=PipelineConfig.default(),
        widget_config={},
    )

    assert set(result.kb_ids) == {kb1.id, kb2.id}
    chatbot_repo.replace_kb_links.assert_awaited_once_with(
        result.id, [kb1.id, kb2.id]
    )


@pytest.mark.asyncio
async def test_create_chatbot_with_incompatible_kbs_rejected() -> None:
    session = MagicMock()
    ctx = _ctx()
    kb_a = _kb_row(_selection_1024())
    kb_b = _kb_row(_selection_768())

    chatbot_repo = MagicMock()
    chatbot_repo.find_by_name = AsyncMock(return_value=None)

    kb_repo = MagicMock()
    kb_repo.get = AsyncMock(side_effect=[kb_a, kb_b])

    with pytest.raises(IncompatibleEmbeddingsError):
        await create_chatbot(
            session, ctx,
            chatbot_repo_factory=lambda s, c: chatbot_repo,
            kb_repo_factory=lambda s, c: kb_repo,
            name="Bot",
            description=None,
            system_prompt="x",
            llm_selection=_llm(),
            kb_ids=[kb_a.id, kb_b.id],
            pipeline_config=PipelineConfig.default(),
            widget_config={},
        )


@pytest.mark.asyncio
async def test_create_chatbot_with_unknown_kb_rejected_as_not_found() -> None:
    from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError

    session = MagicMock()
    ctx = _ctx()
    chatbot_repo = MagicMock()
    chatbot_repo.find_by_name = AsyncMock(return_value=None)
    kb_repo = MagicMock()
    kb_repo.get = AsyncMock(side_effect=NotFoundError("nope"))

    with pytest.raises(KnowledgeBaseNotFoundError):
        await create_chatbot(
            session, ctx,
            chatbot_repo_factory=lambda s, c: chatbot_repo,
            kb_repo_factory=lambda s, c: kb_repo,
            name="Bot",
            description=None,
            system_prompt="x",
            llm_selection=_llm(),
            kb_ids=[uuid4()],
            pipeline_config=PipelineConfig.default(),
            widget_config={},
        )


@pytest.mark.asyncio
async def test_create_chatbot_duplicate_name_rejected() -> None:
    session = MagicMock()
    ctx = _ctx()
    chatbot_repo = MagicMock()
    chatbot_repo.find_by_name = AsyncMock(return_value=MagicMock(name="row"))
    kb_repo = MagicMock()

    with pytest.raises(ChatbotAlreadyExistsError):
        await create_chatbot(
            session, ctx,
            chatbot_repo_factory=lambda s, c: chatbot_repo,
            kb_repo_factory=lambda s, c: kb_repo,
            name="Bot",
            description=None,
            system_prompt="x",
            llm_selection=_llm(),
            kb_ids=[],
            pipeline_config=PipelineConfig.default(),
            widget_config={},
        )


@pytest.mark.asyncio
async def test_update_chatbot_changes_kbs_and_revalidates() -> None:
    session = MagicMock()
    session.flush = AsyncMock()
    ctx = _ctx()
    selection = _selection_1024()
    chatbot_row = MagicMock()
    chatbot_row.id = uuid4()
    chatbot_row.tenant_id = ctx.tenant_id
    chatbot_row.name = "old"
    chatbot_row.description = None
    chatbot_row.system_prompt = "old prompt"
    chatbot_row.llm_selection = _llm().to_dict()
    chatbot_row.router_llm_selection = None
    chatbot_row.pipeline_config = PipelineConfig.default().to_dict()
    chatbot_row.widget_config = {}
    chatbot_row.created_at = None
    chatbot_row.updated_at = None

    chatbot_repo = MagicMock()
    chatbot_repo.get = AsyncMock(return_value=chatbot_row)
    chatbot_repo.list_kb_ids = AsyncMock(return_value=[])
    chatbot_repo.replace_kb_links = AsyncMock()

    kb1, kb2 = _kb_row(selection), _kb_row(selection)
    kb_repo = MagicMock()
    kb_repo.get = AsyncMock(side_effect=[kb1, kb2])

    result = await update_chatbot(
        session, ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: kb_repo,
        chatbot_id=chatbot_row.id,
        name="new",
        description=None,
        system_prompt=None,
        llm_selection=None,
        kb_ids=[kb1.id, kb2.id],
        pipeline_config=None,
        widget_config=None,
    )

    assert result.name == "new"
    chatbot_repo.replace_kb_links.assert_awaited_once_with(
        chatbot_row.id, [kb1.id, kb2.id]
    )


@pytest.mark.asyncio
async def test_update_chatbot_missing_returns_chatbot_not_found() -> None:
    session = MagicMock()
    ctx = _ctx()
    chatbot_repo = MagicMock()
    chatbot_repo.get = AsyncMock(side_effect=NotFoundError("nope"))
    kb_repo = MagicMock()

    with pytest.raises(ChatbotNotFoundError):
        await update_chatbot(
            session, ctx,
            chatbot_repo_factory=lambda s, c: chatbot_repo,
            kb_repo_factory=lambda s, c: kb_repo,
            chatbot_id=uuid4(),
            name="x", description=None, system_prompt=None,
            llm_selection=None, kb_ids=None,
            pipeline_config=None, widget_config=None,
        )


@pytest.mark.asyncio
async def test_list_chatbots_uses_pagination() -> None:
    session = MagicMock()
    ctx = _ctx()
    repo = MagicMock()
    repo.list = AsyncMock(return_value=[])
    repo.list_kb_ids = AsyncMock()  # not called when there are no rows

    await list_chatbots(
        session, ctx,
        chatbot_repo_factory=lambda s, c: repo,
        limit=10, offset=5,
    )

    repo.list.assert_awaited_once_with(limit=10, offset=5)


@pytest.mark.asyncio
async def test_delete_chatbot_calls_repo() -> None:
    session = MagicMock()
    ctx = _ctx()
    repo = MagicMock()
    repo.attempt_delete_with_cascade = AsyncMock()
    chatbot_id = uuid4()

    await delete_chatbot(
        session, ctx,
        chatbot_repo_factory=lambda s, c: repo,
        chatbot_id=chatbot_id,
    )

    repo.attempt_delete_with_cascade.assert_awaited_once_with(chatbot_id)


@pytest.mark.asyncio
async def test_delete_chatbot_missing_raises_chatbot_not_found() -> None:
    from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError

    session = MagicMock()
    ctx = _ctx()
    repo = MagicMock()
    repo.attempt_delete_with_cascade = AsyncMock(
        side_effect=KnowledgeBaseNotFoundError("sentinel")
    )

    with pytest.raises(ChatbotNotFoundError):
        await delete_chatbot(
            session, ctx,
            chatbot_repo_factory=lambda s, c: repo,
            chatbot_id=uuid4(),
        )
```

- [ ] **Step 3.2: Run, confirm collection failure**

```bash
pytest tests/unit/test_chatbot_use_cases.py -v
```

Expected: collection errors — `application/chatbot_config/` does not exist yet.

- [ ] **Step 3.3: Create `backend/src/tfm_rag/application/chatbot_config/__init__.py`** (empty file)

- [ ] **Step 3.4: Create `backend/src/tfm_rag/application/chatbot_config/create_chatbot.py`**

```python
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.chatbot import ChatbotAlreadyExistsError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import (
    IncompatibleEmbeddingsError,
    KnowledgeBaseNotFoundError,
)
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.infrastructure.persistence.models.chatbots import ChatbotRow
from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
    ChatbotRepository,
)
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

ChatbotRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatbotRepository
]
KbRepoFactory = Callable[
    [AsyncSession, RequestContext], KnowledgeBaseRepository
]


def _default_chatbot_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatbotRepository:
    return ChatbotRepository(session, ctx)


def _default_kb_repo(
    session: AsyncSession, ctx: RequestContext
) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session, ctx)


@dataclass(frozen=True, slots=True)
class ChatbotView:
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    system_prompt: str
    llm_selection: LLMSelection
    pipeline_config: PipelineConfig
    widget_config: dict[str, Any]
    kb_ids: list[UUID]


def _to_view(row: ChatbotRow, kb_ids: list[UUID]) -> ChatbotView:
    return ChatbotView(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        description=row.description,
        system_prompt=row.system_prompt,
        llm_selection=LLMSelection.from_dict(row.llm_selection),
        pipeline_config=PipelineConfig.from_dict(row.pipeline_config),
        widget_config=row.widget_config,
        kb_ids=kb_ids,
    )


async def _validate_kb_compatibility(
    kb_repo: KnowledgeBaseRepository, kb_ids: list[UUID]
) -> None:
    """Load each KB (tenant-scoped via repo), enforce that they all share
    the same `embedding_selection` dict.
    """
    if not kb_ids:
        return
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
                f"Attached KBs disagree on embedding_selection. "
                f"Got {first.to_dict()} and {other.to_dict()}."
            )


async def create_chatbot(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    chatbot_repo_factory: ChatbotRepoFactory = _default_chatbot_repo,
    kb_repo_factory: KbRepoFactory = _default_kb_repo,
    name: str,
    description: str | None,
    system_prompt: str,
    llm_selection: LLMSelection,
    kb_ids: list[UUID],
    pipeline_config: PipelineConfig,
    widget_config: dict[str, Any],
) -> ChatbotView:
    name = name.strip()
    if not name:
        from tfm_rag.domain.errors.common import ValidationError
        raise ValidationError("name must not be empty")
    if not system_prompt.strip():
        from tfm_rag.domain.errors.common import ValidationError
        raise ValidationError("system_prompt must not be empty")

    chatbot_repo = chatbot_repo_factory(session, ctx)
    if await chatbot_repo.find_by_name(name) is not None:
        raise ChatbotAlreadyExistsError(
            f"Chatbot named {name!r} already exists in tenant"
        )

    kb_repo = kb_repo_factory(session, ctx)
    await _validate_kb_compatibility(kb_repo, kb_ids)

    chatbot_id = uuid4()
    row = ChatbotRow(
        id=chatbot_id,
        tenant_id=ctx.tenant_id,
        name=name,
        description=description,
        system_prompt=system_prompt,
        llm_selection=llm_selection.to_dict(),
        router_llm_selection=(
            pipeline_config.router_llm_selection.to_dict()
            if pipeline_config.router_llm_selection
            else None
        ),
        pipeline_config=pipeline_config.to_dict(),
        widget_config=widget_config,
    )
    await chatbot_repo.add(row)
    await chatbot_repo.replace_kb_links(chatbot_id, kb_ids)
    return _to_view(row, kb_ids)
```

- [ ] **Step 3.5: Create `backend/src/tfm_rag/application/chatbot_config/update_chatbot.py`**

```python
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.chatbot_config.create_chatbot import (
    ChatbotView,
    _to_view,
    _validate_kb_compatibility,
)
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError, ValidationError
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
    ChatbotRepository,
)
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

ChatbotRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatbotRepository
]
KbRepoFactory = Callable[
    [AsyncSession, RequestContext], KnowledgeBaseRepository
]


def _default_chatbot_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatbotRepository:
    return ChatbotRepository(session, ctx)


def _default_kb_repo(
    session: AsyncSession, ctx: RequestContext
) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session, ctx)


async def update_chatbot(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    chatbot_repo_factory: ChatbotRepoFactory = _default_chatbot_repo,
    kb_repo_factory: KbRepoFactory = _default_kb_repo,
    chatbot_id: UUID,
    name: str | None,
    description: str | None,
    system_prompt: str | None,
    llm_selection: LLMSelection | None,
    kb_ids: list[UUID] | None,
    pipeline_config: PipelineConfig | None,
    widget_config: dict[str, Any] | None,
) -> ChatbotView:
    chatbot_repo = chatbot_repo_factory(session, ctx)
    try:
        row = await chatbot_repo.get(chatbot_id)
    except NotFoundError as exc:
        raise ChatbotNotFoundError(str(exc)) from exc

    if name is not None:
        name = name.strip()
        if not name:
            raise ValidationError("name must not be empty")
        row.name = name
    if description is not None:
        row.description = description or None
    if system_prompt is not None:
        if not system_prompt.strip():
            raise ValidationError("system_prompt must not be empty")
        row.system_prompt = system_prompt
    if llm_selection is not None:
        row.llm_selection = llm_selection.to_dict()
    if pipeline_config is not None:
        row.pipeline_config = pipeline_config.to_dict()
        row.router_llm_selection = (
            pipeline_config.router_llm_selection.to_dict()
            if pipeline_config.router_llm_selection
            else None
        )
    if widget_config is not None:
        row.widget_config = widget_config

    current_kb_ids: list[UUID]
    if kb_ids is not None:
        # Validate the new set and replace the N:M rows.
        kb_repo = kb_repo_factory(session, ctx)
        await _validate_kb_compatibility(kb_repo, kb_ids)
        await chatbot_repo.replace_kb_links(chatbot_id, kb_ids)
        current_kb_ids = kb_ids
    else:
        current_kb_ids = await chatbot_repo.list_kb_ids(chatbot_id)

    await session.flush()
    return _to_view(row, current_kb_ids)
```

- [ ] **Step 3.6: Create `backend/src/tfm_rag/application/chatbot_config/list_chatbots.py`**

```python
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.chatbot_config.create_chatbot import (
    ChatbotView,
    _to_view,
)
from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
    ChatbotRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

ChatbotRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatbotRepository
]


def _default_chatbot_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatbotRepository:
    return ChatbotRepository(session, ctx)


async def list_chatbots(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    chatbot_repo_factory: ChatbotRepoFactory = _default_chatbot_repo,
    limit: int = 20,
    offset: int = 0,
) -> list[ChatbotView]:
    repo = chatbot_repo_factory(session, ctx)
    rows = await repo.list(limit=limit, offset=offset)
    views: list[ChatbotView] = []
    for row in rows:
        kb_ids = await repo.list_kb_ids(row.id)
        views.append(_to_view(row, kb_ids))
    return views
```

- [ ] **Step 3.7: Create `backend/src/tfm_rag/application/chatbot_config/get_chatbot.py`**

```python
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.chatbot_config.create_chatbot import (
    ChatbotView,
    _to_view,
)
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
    ChatbotRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

ChatbotRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatbotRepository
]


def _default_chatbot_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatbotRepository:
    return ChatbotRepository(session, ctx)


async def get_chatbot(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    chatbot_repo_factory: ChatbotRepoFactory = _default_chatbot_repo,
    chatbot_id: UUID,
) -> ChatbotView:
    repo = chatbot_repo_factory(session, ctx)
    try:
        row = await repo.get(chatbot_id)
    except NotFoundError as exc:
        raise ChatbotNotFoundError(str(exc)) from exc
    kb_ids = await repo.list_kb_ids(chatbot_id)
    return _to_view(row, kb_ids)
```

- [ ] **Step 3.8: Create `backend/src/tfm_rag/application/chatbot_config/delete_chatbot.py`**

```python
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.knowledge import KnowledgeBaseNotFoundError
from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
    ChatbotRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

ChatbotRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatbotRepository
]


def _default_chatbot_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatbotRepository:
    return ChatbotRepository(session, ctx)


async def delete_chatbot(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    chatbot_repo_factory: ChatbotRepoFactory = _default_chatbot_repo,
    chatbot_id: UUID,
) -> None:
    repo = chatbot_repo_factory(session, ctx)
    try:
        await repo.attempt_delete_with_cascade(chatbot_id)
    except KnowledgeBaseNotFoundError as exc:
        # The repo uses that error as a sentinel for "row not found".
        # Translate to the chatbot-scoped error so callers get the right
        # 404 message.
        raise ChatbotNotFoundError(
            f"Chatbot({chatbot_id}) not found in tenant"
        ) from exc
```

- [ ] **Step 3.9: Run the unit tests, confirm they pass**

```bash
pytest tests/unit/test_chatbot_use_cases.py -v
```

Expected: **10 PASSED**.

- [ ] **Step 3.10: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/application/chatbot_config backend/tests/unit/test_chatbot_use_cases.py
git commit -m "feat(chatbot_config): CreateChatbot/UpdateChatbot/List/Get/DeleteChatbot use cases"
```

---

## Task 4 — API: `/api/chatbots/*`

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/api/routers/chatbots.py`
- Modify: `backend/src/tfm_rag/infrastructure/api/app.py` (mount the new router)

- [ ] **Step 4.1: Create `backend/src/tfm_rag/infrastructure/api/routers/chatbots.py`**

```python
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.chatbot_config.create_chatbot import (
    ChatbotView,
    create_chatbot,
)
from tfm_rag.application.chatbot_config.delete_chatbot import delete_chatbot
from tfm_rag.application.chatbot_config.get_chatbot import get_chatbot
from tfm_rag.application.chatbot_config.list_chatbots import list_chatbots
from tfm_rag.application.chatbot_config.update_chatbot import update_chatbot
from tfm_rag.domain.errors.chatbot import (
    ChatbotAlreadyExistsError,
    ChatbotNotFoundError,
)
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.errors.knowledge import (
    IncompatibleEmbeddingsError,
    KnowledgeBaseNotFoundError,
)
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import (
    GenerationConfig,
    PipelineConfig,
)
from tfm_rag.infrastructure.api.dependencies import (
    get_current_context,
    get_session,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

router = APIRouter(prefix="/api/chatbots", tags=["chatbots"])


# --- Input models -----------------------------------------------------------

class LLMSelectionIn(BaseModel):
    provider_id: str
    credential_id: UUID
    model_id: str

    def to_vo(self) -> LLMSelection:
        return LLMSelection(
            provider_id=self.provider_id,
            credential_id=self.credential_id,
            model_id=self.model_id,
        )


class GenerationConfigIn(BaseModel):
    temperature: float = 0.2
    top_p: float = 1.0
    max_tokens: int = Field(default=1024, ge=1, le=32_000)

    def to_vo(self) -> GenerationConfig:
        return GenerationConfig(
            temperature=self.temperature,
            top_p=self.top_p,
            max_tokens=self.max_tokens,
        )


class PipelineConfigIn(BaseModel):
    top_k: int = Field(default=5, ge=1, le=50)
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    agentic_mode: bool = True
    max_retrieval_iterations: int = Field(default=3, ge=1, le=5)
    enable_reranker: bool = False
    reranker_initial_top_k: int = Field(default=30, ge=1, le=200)
    abstain_when_insufficient: bool = True
    router_llm_selection: LLMSelectionIn | None = None
    generation: GenerationConfigIn = Field(default_factory=GenerationConfigIn)

    def to_vo(self) -> PipelineConfig:
        return PipelineConfig(
            top_k=self.top_k,
            score_threshold=self.score_threshold,
            agentic_mode=self.agentic_mode,
            max_retrieval_iterations=self.max_retrieval_iterations,
            enable_reranker=self.enable_reranker,
            reranker_initial_top_k=self.reranker_initial_top_k,
            abstain_when_insufficient=self.abstain_when_insufficient,
            router_llm_selection=(
                self.router_llm_selection.to_vo()
                if self.router_llm_selection
                else None
            ),
            generation=self.generation.to_vo(),
        )


class CreateChatbotIn(BaseModel):
    name: str
    description: str | None = None
    system_prompt: str
    llm_selection: LLMSelectionIn
    kb_ids: list[UUID] = Field(default_factory=list)
    pipeline_config: PipelineConfigIn = Field(default_factory=PipelineConfigIn)
    widget_config: dict[str, Any] = Field(default_factory=dict)


class UpdateChatbotIn(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    llm_selection: LLMSelectionIn | None = None
    kb_ids: list[UUID] | None = None
    pipeline_config: PipelineConfigIn | None = None
    widget_config: dict[str, Any] | None = None


# --- Output models ----------------------------------------------------------

class ChatbotOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: str | None
    system_prompt: str
    llm_selection: dict[str, Any]
    pipeline_config: dict[str, Any]
    widget_config: dict[str, Any]
    kb_ids: list[str]

    @classmethod
    def from_view(cls, v: ChatbotView) -> "ChatbotOut":
        return cls(
            id=str(v.id),
            tenant_id=str(v.tenant_id),
            name=v.name,
            description=v.description,
            system_prompt=v.system_prompt,
            llm_selection=v.llm_selection.to_dict(),
            pipeline_config=v.pipeline_config.to_dict(),
            widget_config=v.widget_config,
            kb_ids=[str(i) for i in v.kb_ids],
        )


# --- Routes -----------------------------------------------------------------

@router.post("", status_code=201, response_model=ChatbotOut)
async def create_(
    body: CreateChatbotIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> ChatbotOut:
    try:
        view = await create_chatbot(
            session, ctx,
            name=body.name,
            description=body.description,
            system_prompt=body.system_prompt,
            llm_selection=body.llm_selection.to_vo(),
            kb_ids=body.kb_ids,
            pipeline_config=body.pipeline_config.to_vo(),
            widget_config=body.widget_config,
        )
    except ChatbotAlreadyExistsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IncompatibleEmbeddingsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ChatbotOut.from_view(view)


@router.get("", response_model=list[ChatbotOut])
async def list_(
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> list[ChatbotOut]:
    views = await list_chatbots(session, ctx, limit=limit, offset=offset)
    return [ChatbotOut.from_view(v) for v in views]


@router.get("/{chatbot_id}", response_model=ChatbotOut)
async def get_(
    chatbot_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> ChatbotOut:
    try:
        view = await get_chatbot(session, ctx, chatbot_id=chatbot_id)
    except ChatbotNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ChatbotOut.from_view(view)


@router.patch("/{chatbot_id}", response_model=ChatbotOut)
async def patch_(
    chatbot_id: UUID,
    body: UpdateChatbotIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> ChatbotOut:
    try:
        view = await update_chatbot(
            session, ctx,
            chatbot_id=chatbot_id,
            name=body.name,
            description=body.description,
            system_prompt=body.system_prompt,
            llm_selection=body.llm_selection.to_vo() if body.llm_selection else None,
            kb_ids=body.kb_ids,
            pipeline_config=body.pipeline_config.to_vo() if body.pipeline_config else None,
            widget_config=body.widget_config,
        )
    except ChatbotNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except IncompatibleEmbeddingsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ChatbotOut.from_view(view)


@router.delete("/{chatbot_id}", status_code=204)
async def delete_(
    chatbot_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> None:
    try:
        await delete_chatbot(session, ctx, chatbot_id=chatbot_id)
    except ChatbotNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
```

- [ ] **Step 4.2: Mount the router in `backend/src/tfm_rag/infrastructure/api/app.py`**

Replace the existing `from tfm_rag.infrastructure.api.routers import (...)` block + the `include_router` calls inside `create_app`. The final shape should be:

```python
from fastapi import FastAPI

from tfm_rag.infrastructure.api.middleware.tenant_scoping import (
    TenantScopingMiddleware,
)
from tfm_rag.infrastructure.api.routers import (
    auth,
    chatbots,
    credentials,
    health,
    ingestion_jobs,
    knowledge_bases,
)
from tfm_rag.infrastructure.settings import get_settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="TFM RAG Chatbot Platform",
        version="0.1.0",
    )
    settings = get_settings()
    app.add_middleware(TenantScopingMiddleware, settings=settings)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(credentials.router)
    app.include_router(knowledge_bases.router)
    app.include_router(ingestion_jobs.router)
    app.include_router(chatbots.router)
    return app


app = create_app()
```

- [ ] **Step 4.3: Verify the app imports cleanly**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
python -c "from tfm_rag.infrastructure.api.app import app; print(app.title)"
```

Expected: prints `TFM RAG Chatbot Platform`. No ImportError.

- [ ] **Step 4.4: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/infrastructure/api/routers/chatbots.py backend/src/tfm_rag/infrastructure/api/app.py
git commit -m "feat(api): /api/chatbots/* (CRUD with embedding-compat validation)"
```

---

## Task 5 — Integration tests: full lifecycle + cross-KB rule + tenant isolation + KB-in-use cascade

This task exercises the end-to-end path against the live stack:
- create chatbot with 0 KBs
- create chatbot with 1 KB
- create chatbot with 2 KBs same dim
- create chatbot with 2 KBs different dim → 409
- list / get / patch / delete
- delete a KB that's referenced → 409 `KnowledgeBaseInUseError` (verifies that plan #7's catch now fires because the FK exists)

**Files:**
- Create: `backend/tests/integration/test_chatbot_endpoints.py`

- [ ] **Step 5.1: Write the integration test**

Create `backend/tests/integration/test_chatbot_endpoints.py`:

```python
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


async def _ollama_cred_id(client: AsyncClient, token: str) -> str:
    r = await client.get(
        "/api/credentials",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    return next(c for c in r.json() if c["provider_id"] == "ollama")["id"]


async def _create_kb(
    client: AsyncClient, token: str, name: str, dim: int, model_id: str
) -> str:
    cred = await _ollama_cred_id(client, token)
    r = await client.post(
        "/api/knowledge-bases",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": name,
            "embedding_selection": {
                "provider_id": "ollama",
                "credential_id": cred,
                "model_id": model_id,
                "dim": dim,
            },
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.integration
async def test_chatbot_full_lifecycle(_clean_state: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, _ = await _register(client, "bot-owner@example.com")
        cred = await _ollama_cred_id(client, token)
        h = {"Authorization": f"Bearer {token}"}

        # 0-KB chatbot
        r = await client.post(
            "/api/chatbots", headers=h,
            json={
                "name": "LLM-only",
                "system_prompt": "Be concise.",
                "llm_selection": {
                    "provider_id": "ollama",
                    "credential_id": cred,
                    "model_id": "llama3.1",
                },
                "kb_ids": [],
                "widget_config": {"theme": "light"},
            },
        )
        assert r.status_code == 201, r.text
        bot1 = r.json()
        assert bot1["kb_ids"] == []
        assert bot1["pipeline_config"]["max_retrieval_iterations"] == 3
        assert bot1["pipeline_config"]["agentic_mode"] is True

        # KB + chatbot with KB
        kb1 = await _create_kb(client, token, "Manuals", 1024, "bge-m3")
        r = await client.post(
            "/api/chatbots", headers=h,
            json={
                "name": "ManualsBot",
                "system_prompt": "Answer with citations.",
                "llm_selection": {
                    "provider_id": "ollama",
                    "credential_id": cred,
                    "model_id": "llama3.1",
                },
                "kb_ids": [kb1],
                "widget_config": {},
            },
        )
        assert r.status_code == 201, r.text
        bot2 = r.json()
        assert bot2["kb_ids"] == [kb1]

        # Duplicate name → 409
        r = await client.post(
            "/api/chatbots", headers=h,
            json={
                "name": "ManualsBot",
                "system_prompt": "x",
                "llm_selection": {
                    "provider_id": "ollama",
                    "credential_id": cred,
                    "model_id": "llama3.1",
                },
                "kb_ids": [],
                "widget_config": {},
            },
        )
        assert r.status_code == 409, r.text

        # List
        r = await client.get("/api/chatbots", headers=h)
        assert r.status_code == 200
        ids = {b["id"] for b in r.json()}
        assert {bot1["id"], bot2["id"]} <= ids

        # Get
        r = await client.get(f"/api/chatbots/{bot2['id']}", headers=h)
        assert r.status_code == 200
        assert r.json()["kb_ids"] == [kb1]

        # Patch — change name + pipeline_config.max_retrieval_iterations
        r = await client.patch(
            f"/api/chatbots/{bot2['id']}", headers=h,
            json={
                "name": "ManualsBot v2",
                "pipeline_config": {
                    "top_k": 7,
                    "max_retrieval_iterations": 5,
                    "score_threshold": 0.2,
                    "agentic_mode": True,
                    "enable_reranker": False,
                    "reranker_initial_top_k": 30,
                    "abstain_when_insufficient": True,
                    "generation": {
                        "temperature": 0.1,
                        "top_p": 0.95,
                        "max_tokens": 2048,
                    },
                },
            },
        )
        assert r.status_code == 200, r.text
        patched = r.json()
        assert patched["name"] == "ManualsBot v2"
        assert patched["pipeline_config"]["max_retrieval_iterations"] == 5

        # Delete
        r = await client.delete(f"/api/chatbots/{bot1['id']}", headers=h)
        assert r.status_code == 204
        r = await client.get(f"/api/chatbots/{bot1['id']}", headers=h)
        assert r.status_code == 404


@pytest.mark.integration
async def test_chatbot_rejects_incompatible_embeddings(_clean_state: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, _ = await _register(client, "owner2@example.com")
        cred = await _ollama_cred_id(client, token)
        h = {"Authorization": f"Bearer {token}"}

        kb_1024 = await _create_kb(client, token, "KB-1024", 1024, "bge-m3")
        kb_768 = await _create_kb(
            client, token, "KB-768", 768, "nomic-embed-text"
        )

        r = await client.post(
            "/api/chatbots", headers=h,
            json={
                "name": "MixedBot",
                "system_prompt": "x",
                "llm_selection": {
                    "provider_id": "ollama",
                    "credential_id": cred,
                    "model_id": "llama3.1",
                },
                "kb_ids": [kb_1024, kb_768],
                "widget_config": {},
            },
        )
        assert r.status_code == 409
        assert "embedding" in r.json()["detail"].lower()


@pytest.mark.integration
async def test_delete_kb_referenced_by_chatbot_returns_409(_clean_state: None) -> None:
    """Verifies that plan #7's KnowledgeBaseInUseError mapping fires once
    the RESTRICT FK exists.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, _ = await _register(client, "owner3@example.com")
        cred = await _ollama_cred_id(client, token)
        h = {"Authorization": f"Bearer {token}"}

        kb = await _create_kb(client, token, "Locked", 1024, "bge-m3")
        r = await client.post(
            "/api/chatbots", headers=h,
            json={
                "name": "Bot",
                "system_prompt": "x",
                "llm_selection": {
                    "provider_id": "ollama",
                    "credential_id": cred,
                    "model_id": "llama3.1",
                },
                "kb_ids": [kb],
                "widget_config": {},
            },
        )
        assert r.status_code == 201, r.text
        bot_id = r.json()["id"]

        # Try to delete the KB → 409
        r = await client.delete(f"/api/knowledge-bases/{kb}", headers=h)
        assert r.status_code == 409, r.text
        assert "referenc" in r.json()["detail"].lower()

        # Delete the chatbot first; THEN the KB delete succeeds
        r = await client.delete(f"/api/chatbots/{bot_id}", headers=h)
        assert r.status_code == 204
        r = await client.delete(f"/api/knowledge-bases/{kb}", headers=h)
        assert r.status_code == 204


@pytest.mark.integration
async def test_chatbot_isolation_between_tenants(_clean_state: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        alice_token, _ = await _register(client, "alice-bot@example.com")
        bob_token, _ = await _register(client, "bob-bot@example.com")
        alice_cred = await _ollama_cred_id(client, alice_token)

        # Alice creates a chatbot
        r = await client.post(
            "/api/chatbots",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={
                "name": "Alice Bot",
                "system_prompt": "x",
                "llm_selection": {
                    "provider_id": "ollama",
                    "credential_id": alice_cred,
                    "model_id": "llama3.1",
                },
                "kb_ids": [],
                "widget_config": {},
            },
        )
        assert r.status_code == 201
        bot_id = r.json()["id"]

        # Bob cannot see it
        r = await client.get(
            "/api/chatbots",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert r.status_code == 200
        assert r.json() == []

        # Nor fetch it by id
        r = await client.get(
            f"/api/chatbots/{bot_id}",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert r.status_code == 404
```

- [ ] **Step 5.2: Reset DB and run the integration test**

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
pytest tests/integration/test_chatbot_endpoints.py -m integration -v
```

Expected: **4 PASSED**.

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

Expected: previous 12 + 1 chatbots-migration + 4 chatbot endpoints = **17 PASSED**.

- [ ] **Step 5.4: Commit + tag**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/tests/integration/test_chatbot_endpoints.py
git commit -m "test(chatbots): integration tests for CRUD + embedding-compat + KB-in-use + tenant isolation"
git tag cap-10-chatbot-lifecycle
```

---

## What's next (deferred, for handover)

After this plan ships:

- **Plan #11 (CAP-CHATBOT-WIDGET-CONFIG)** introduces a strict `WidgetConfig` VO + `UpdateWidgetConfig`/`GetPublicWidgetConfig` use cases + `PATCH /api/chatbots/{id}/widget-config` + `GET /api/public/chatbots/{id}/widget-config`. Plan #10's `widget_config: dict[str, Any]` is forward-compatible: existing rows survive the migration to the typed VO because we'll add a `from_dict` that tolerates loose dicts.
- **Plan #12 (CAP-CHAT-DOC-RETRIEVAL)** ships `RetrieveDocs(kb_ids, query, top_k, threshold)` — the search side of M3 — embedding the query, hitting Qdrant with `tenant_id + kb_ids` filters, optional reranker. The Qdrant collection name resolution uses `chatbot.kb_ids[0].embedding_selection.dim` (the cross-KB rule plan #10 enforces guarantees a single dim).
- **Plan #14 (CAP-CHAT-SESSIONS)** adds `chat_sessions` + `chat_messages` tables. Plan #10's `DeleteChatbot` already cascades the chatbot row; once #14 adds those tables with `ON DELETE CASCADE` on chatbot_id, the spec's "cascada sesiones + mensajes" wording becomes literally true with no code change in #10.
- **Plan #15 (CAP-CHAT-AGENT-LOOP)** is what ties it all together: takes a chatbot's `llm_selection` + `pipeline_config`, runs the agent loop over the attached KBs, persists `RetrievalIteration[]` in `ChatMessage.metadata`.
