# CAP-CHATBOT-WIDGET-CONFIG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the opaque `chatbot.widget_config: dict[str, Any]` with a typed `WidgetConfig` VO (theme, colors, copy, allowed origins), add a unique **`public_key`** column to `chatbots` so plan #16's `/api/public/chatbots/{public_key}/chat` endpoint can identify the bot without a JWT, and expose a `get_chatbot_by_public_key` helper for plan #16 to consume.

**Architecture:** Adds one VO (`WidgetConfig`) with validation. Adds one migration: `public_key VARCHAR(64) NOT NULL UNIQUE` on `chatbots`. Generates the key in `create_chatbot` (one-off, immutable; PATCH ignores any incoming `public_key`). The HTTP layer accepts and emits a structured `WidgetConfigIn` / `WidgetConfigOut` Pydantic model. Adds CORS middleware (permissive default for `/api/public/*`; plan #16 will narrow it per-chatbot via `allowed_origins`). The `get_chatbot_by_public_key` helper is a use-case wrapper around a new `ChatbotRepository.get_by_public_key` method and intentionally does NOT filter by tenant — plan #16 derives the tenant FROM the chatbot row it loads.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, secrets module, pytest.

---

## File structure

**New files:**

- `backend/src/tfm_rag/domain/value_objects/widget_config.py` — `WidgetConfig` VO + enums + validators.
- `backend/src/tfm_rag/application/chatbot_config/get_chatbot_by_public_key.py` — public-key lookup use case (returns full `Chatbot` entity, no tenant filter).
- `backend/alembic/versions/0009_chatbots_public_key.py` — migration adding the column + index + unique constraint + backfill.
- `backend/tests/unit/test_widget_config_vo.py`
- `backend/tests/unit/test_get_chatbot_by_public_key.py`
- `backend/tests/integration/test_chatbot_widget_config_endpoints.py`

**Modified files:**

- `backend/src/tfm_rag/domain/entities/chatbot.py` — change `widget_config: dict[str, Any]` → `widget_config: WidgetConfig`. Add `public_key: str` field.
- `backend/src/tfm_rag/infrastructure/persistence/models/chatbots.py` — add `public_key: Mapped[str]` column.
- `backend/src/tfm_rag/infrastructure/persistence/repositories/chatbots_repo.py` — add `get_by_public_key(public_key) -> ChatbotRow` method.
- `backend/src/tfm_rag/application/chatbot_config/create_chatbot.py` — accept `WidgetConfig`, generate `public_key`, persist both. Return new fields in view.
- `backend/src/tfm_rag/application/chatbot_config/update_chatbot.py` — accept `WidgetConfig | None`, persist if provided. Ignore any incoming `public_key` (immutable).
- `backend/src/tfm_rag/application/chatbot_config/get_chatbot.py` — return `WidgetConfig` + `public_key` in the view.
- `backend/src/tfm_rag/application/chatbot_config/list_chatbots.py` — same.
- `backend/src/tfm_rag/infrastructure/api/routers/chatbots.py` — add `WidgetConfigIn`/`WidgetConfigOut` Pydantic models; add `public_key` to `ChatbotOut`; drop the loose `dict[str, Any]` shape.
- `backend/src/tfm_rag/infrastructure/api/app.py` — add CORS middleware (permissive default for `/api/public/*`).
- `backend/tests/unit/test_chatbot_use_cases.py` — update fixtures to use structured `WidgetConfig` + assert `public_key` is generated.
- `backend/tests/integration/test_chatbot_endpoints.py` — update existing assertions to the new shape; add assertions for `public_key` immutability.

**Out of scope** (deferred to plan #16):

- The `/api/public/chatbots/{public_key}/chat` endpoint (uses the helper we expose here, not ours to ship).
- The HTML widget itself + the embeddable snippet generator.
- Per-chatbot CORS origin narrowing — plan #11 ships CORS as **permissive** (`*` for `/api/public/*` paths) so plan #16 can demo before tightening.
- Live preview in the panel (purely frontend).
- Rotating `public_key` (no UI for it; only changeable via DB).

---

## Task 1 — Domain: `WidgetConfig` VO + validation

**Files:**
- Create: `backend/src/tfm_rag/domain/value_objects/widget_config.py`
- Create: `backend/tests/unit/test_widget_config_vo.py`

### Step 1.1: Write the failing test

Create `backend/tests/unit/test_widget_config_vo.py`:

```python
"""Unit tests for the WidgetConfig VO."""
import pytest

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.widget_config import (
    WidgetConfig,
    WidgetPosition,
    WidgetTheme,
)


# --- happy path ----------------------------------------------------------------


def test_defaults_are_sane() -> None:
    cfg = WidgetConfig.default()
    assert cfg.theme == "light"
    assert cfg.position == "bottom-right"
    assert cfg.primary_color == "#3b82f6"
    assert cfg.title  # non-empty
    assert cfg.welcome_message  # non-empty
    assert cfg.placeholder  # non-empty
    assert cfg.allowed_origins == ()


def test_round_trip_to_dict_and_back() -> None:
    cfg = WidgetConfig(
        theme="dark",
        primary_color="#10B981",
        position="bottom-left",
        title="Help",
        welcome_message="Hi!",
        placeholder="Ask...",
        allowed_origins=("https://example.com", "https://other.example.com"),
    )
    data = cfg.to_dict()
    assert data == {
        "theme": "dark",
        "primary_color": "#10B981",
        "position": "bottom-left",
        "title": "Help",
        "welcome_message": "Hi!",
        "placeholder": "Ask...",
        "allowed_origins": ["https://example.com", "https://other.example.com"],
    }
    assert WidgetConfig.from_dict(data) == cfg


def test_from_dict_with_missing_keys_falls_back_to_defaults() -> None:
    # Backwards compat: existing rows in DB may carry partial dicts.
    cfg = WidgetConfig.from_dict({"theme": "dark"})
    assert cfg.theme == "dark"
    assert cfg.position == "bottom-right"  # default
    assert cfg.primary_color == "#3b82f6"  # default


def test_from_dict_with_empty_dict_returns_default() -> None:
    cfg = WidgetConfig.from_dict({})
    assert cfg == WidgetConfig.default()


def test_typed_enums_via_dataclass_field() -> None:
    # Literal types narrowed via type aliases (no runtime check needed)
    cfg = WidgetConfig.default()
    assert isinstance(cfg.theme, str)
    assert isinstance(cfg.position, str)


# --- validation: theme + position ---------------------------------------------


def test_invalid_theme_raises_validation_error() -> None:
    with pytest.raises(ValidationError) as exc_info:
        WidgetConfig.from_dict({"theme": "neon"})
    assert "theme" in str(exc_info.value).lower()


def test_invalid_position_raises_validation_error() -> None:
    with pytest.raises(ValidationError) as exc_info:
        WidgetConfig.from_dict({"position": "top-right"})
    assert "position" in str(exc_info.value).lower()


# --- validation: primary_color hex --------------------------------------------


@pytest.mark.parametrize(
    "color",
    [
        "#3b82f6",
        "#3B82F6",
        "#FFFFFF",
        "#000000",
        "#ABC",  # 3-digit shorthand allowed
    ],
)
def test_valid_hex_colors_accepted(color: str) -> None:
    cfg = WidgetConfig.from_dict({"primary_color": color})
    assert cfg.primary_color == color


@pytest.mark.parametrize(
    "color",
    [
        "3b82f6",     # missing '#'
        "#GGGGGG",    # non-hex chars
        "#12345",     # 5-digit
        "#1234567",   # 7-digit
        "blue",       # name
        "",
    ],
)
def test_invalid_hex_colors_rejected(color: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        WidgetConfig.from_dict({"primary_color": color})
    assert "primary_color" in str(exc_info.value).lower() or "color" in str(exc_info.value).lower()


# --- validation: string lengths -----------------------------------------------


def test_title_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        WidgetConfig.from_dict({"title": "x" * 100})  # cap at 60 chars


def test_welcome_message_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        WidgetConfig.from_dict({"welcome_message": "x" * 1000})  # cap at 500


def test_placeholder_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        WidgetConfig.from_dict({"placeholder": "x" * 200})  # cap at 100


def test_empty_title_rejected() -> None:
    with pytest.raises(ValidationError):
        WidgetConfig.from_dict({"title": ""})


# --- validation: allowed_origins ----------------------------------------------


@pytest.mark.parametrize(
    "origin",
    [
        "https://example.com",
        "http://localhost:3000",
        "https://sub.example.co.uk",
        "*",  # wildcard allowed
    ],
)
def test_valid_origins_accepted(origin: str) -> None:
    cfg = WidgetConfig.from_dict({"allowed_origins": [origin]})
    assert origin in cfg.allowed_origins


@pytest.mark.parametrize(
    "origin",
    [
        "example.com",         # missing scheme
        "https://",            # empty host
        "ftp://example.com",   # disallowed scheme
        "https://example.com/path",  # path not allowed
        "https://example.com:",   # trailing colon
    ],
)
def test_invalid_origins_rejected(origin: str) -> None:
    with pytest.raises(ValidationError):
        WidgetConfig.from_dict({"allowed_origins": [origin]})


def test_too_many_origins_rejected() -> None:
    many = [f"https://h{i}.example.com" for i in range(60)]
    with pytest.raises(ValidationError):
        WidgetConfig.from_dict({"allowed_origins": many})  # cap at 50


def test_duplicate_origins_deduplicated() -> None:
    cfg = WidgetConfig.from_dict({
        "allowed_origins": ["https://a.example.com", "https://a.example.com"],
    })
    assert cfg.allowed_origins == ("https://a.example.com",)
```

Run the test (expect ImportError on `widget_config`):

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
pytest tests/unit/test_widget_config_vo.py -v 2>&1 | tail -10
```

### Step 1.2: Implement `WidgetConfig` VO

Create `backend/src/tfm_rag/domain/value_objects/widget_config.py`:

```python
"""WidgetConfig — typed shape for the embeddable chat widget settings.

Persisted as a JSONB column on the chatbots table. The chatbot owner edits
this from the panel; plan #16's widget runtime reads it from the public
chat endpoint response to style the embed.
"""
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from tfm_rag.domain.errors.common import ValidationError

WidgetTheme = Literal["light", "dark"]
WidgetPosition = Literal["bottom-right", "bottom-left"]

_THEMES: tuple[str, ...] = ("light", "dark")
_POSITIONS: tuple[str, ...] = ("bottom-right", "bottom-left")

_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
# A permissive origin matcher: scheme + host (+ optional port). No path,
# no fragment, no query. Wildcard '*' is accepted as a separate sentinel.
_ORIGIN_RE = re.compile(
    r"^https?://"
    r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)*"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?"
    r"(?::\d{1,5})?$"
)

_MAX_TITLE = 60
_MAX_WELCOME = 500
_MAX_PLACEHOLDER = 100
_MAX_ORIGINS = 50


@dataclass(frozen=True, slots=True)
class WidgetConfig:
    theme: WidgetTheme = "light"
    primary_color: str = "#3b82f6"
    position: WidgetPosition = "bottom-right"
    title: str = "Asistente"
    welcome_message: str = "¿En qué puedo ayudarte?"
    placeholder: str = "Escribe tu pregunta..."
    allowed_origins: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _validate_enum("theme", self.theme, _THEMES)
        _validate_enum("position", self.position, _POSITIONS)
        _validate_color(self.primary_color)
        _validate_str_len("title", self.title, 1, _MAX_TITLE)
        _validate_str_len("welcome_message", self.welcome_message, 1, _MAX_WELCOME)
        _validate_str_len("placeholder", self.placeholder, 1, _MAX_PLACEHOLDER)
        _validate_origins(self.allowed_origins)

    @classmethod
    def default(cls) -> "WidgetConfig":
        return cls()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WidgetConfig":
        """Build a WidgetConfig from a (possibly partial) dict.

        Missing keys fall back to defaults — important for old chatbots
        in DB that were stored with `widget_config={}` or `{"theme": "light"}`.
        Duplicates in allowed_origins are deduplicated.
        """
        defaults = cls.default()
        origins_raw = data.get("allowed_origins")
        origins: tuple[str, ...]
        if origins_raw is None:
            origins = defaults.allowed_origins
        else:
            if not isinstance(origins_raw, (list, tuple)):
                raise ValidationError(
                    f"allowed_origins must be a list, got {type(origins_raw).__name__}"
                )
            # Dedupe but preserve first-seen order.
            seen: dict[str, None] = {}
            for o in origins_raw:
                if not isinstance(o, str):
                    raise ValidationError("allowed_origins entries must be strings")
                seen.setdefault(o, None)
            origins = tuple(seen.keys())

        return cls(
            theme=data.get("theme", defaults.theme),
            primary_color=data.get("primary_color", defaults.primary_color),
            position=data.get("position", defaults.position),
            title=data.get("title", defaults.title),
            welcome_message=data.get("welcome_message", defaults.welcome_message),
            placeholder=data.get("placeholder", defaults.placeholder),
            allowed_origins=origins,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "theme": self.theme,
            "primary_color": self.primary_color,
            "position": self.position,
            "title": self.title,
            "welcome_message": self.welcome_message,
            "placeholder": self.placeholder,
            "allowed_origins": list(self.allowed_origins),
        }


def _validate_enum(field: str, value: Any, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise ValidationError(
            f"{field} must be one of {allowed!r}, got {value!r}"
        )


def _validate_color(value: Any) -> None:
    if not isinstance(value, str) or not _HEX_COLOR_RE.match(value):
        raise ValidationError(
            f"primary_color must be a hex string like '#3b82f6', got {value!r}"
        )


def _validate_str_len(field: str, value: Any, lo: int, hi: int) -> None:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string, got {type(value).__name__}")
    n = len(value)
    if n < lo:
        raise ValidationError(f"{field} too short ({n} < {lo})")
    if n > hi:
        raise ValidationError(f"{field} too long ({n} > {hi})")


def _validate_origins(origins: tuple[str, ...]) -> None:
    if len(origins) > _MAX_ORIGINS:
        raise ValidationError(
            f"allowed_origins exceeds max of {_MAX_ORIGINS}: got {len(origins)}"
        )
    for o in origins:
        if o == "*":
            continue
        if not _ORIGIN_RE.match(o):
            raise ValidationError(
                f"allowed_origins entry {o!r} is not a valid origin "
                f"(must be like 'https://host' or 'http://host:port', no path/query)"
            )
```

### Step 1.3: Run the test

```bash
pytest tests/unit/test_widget_config_vo.py -v 2>&1 | tail -25
```

Expected: **all ~23 tests pass** (some parametrized).

### Step 1.4: Commit

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/domain/value_objects/widget_config.py \
        backend/tests/unit/test_widget_config_vo.py
git commit -m "feat(domain): WidgetConfig VO + validation + tests (plan #11 Task 1)"
```

---

## Task 2 — Persistence: migration + repo helper

**Files:**
- Create: `backend/alembic/versions/0009_chatbots_public_key.py`
- Modify: `backend/src/tfm_rag/infrastructure/persistence/models/chatbots.py`
- Modify: `backend/src/tfm_rag/infrastructure/persistence/repositories/chatbots_repo.py`

### Step 2.1: Add the `public_key` column on the ORM model

Open `backend/src/tfm_rag/infrastructure/persistence/models/chatbots.py`. Add the new column right after `widget_config`:

```python
    widget_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    public_key: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
```

Do NOT modify any other column. The existing migration that created the table (`0006_chatbots_and_n2m.py`) stays untouched.

### Step 2.2: Write the migration

First, check the latest existing migration so the `down_revision` points at it correctly:

```bash
ls backend/alembic/versions/ | sort | tail -5
```

The latest is `0008_*.py` (or similar — check the actual list). If it's actually `0007`, name the new migration `0008_chatbots_public_key.py` and point `down_revision` at `'0007'`. The plan assumes the next number is `0009`; adapt if needed.

Create `backend/alembic/versions/0009_chatbots_public_key.py`:

```python
"""Add public_key column to chatbots.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-25
"""
import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Step 1: add as nullable so we can backfill existing rows (if any).
    op.add_column(
        "chatbots",
        sa.Column("public_key", sa.String(length=64), nullable=True),
    )

    # Step 2: backfill any existing rows with random unique values.
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id FROM chatbots WHERE public_key IS NULL")
    ).fetchall()
    for row in rows:
        chatbot_id = row[0]
        conn.execute(
            sa.text(
                "UPDATE chatbots SET public_key = :pk WHERE id = :id"
            ),
            {"pk": "wgt_" + secrets.token_urlsafe(32), "id": chatbot_id},
        )

    # Step 3: enforce NOT NULL + UNIQUE.
    op.alter_column("chatbots", "public_key", nullable=False)
    op.create_unique_constraint(
        "uq_chatbots_public_key", "chatbots", ["public_key"]
    )
    op.create_index(
        "ix_chatbots_public_key", "chatbots", ["public_key"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_chatbots_public_key", table_name="chatbots")
    op.drop_constraint("uq_chatbots_public_key", "chatbots", type_="unique")
    op.drop_column("chatbots", "public_key")
```

If the latest existing migration ID is NOT `0008`, change `down_revision: str | None = "0008"` to the actual latest ID, AND rename the new file to `<latest+1>_chatbots_public_key.py`. Verify by reading the latest migration file: `head -10 backend/alembic/versions/0008_*.py`.

### Step 2.3: Add `get_by_public_key` to the ORM repository

Open `backend/src/tfm_rag/infrastructure/persistence/repositories/chatbots_repo.py`. Find the existing `ChatbotRepository` class. Add this method (do NOT modify existing methods):

```python
    async def get_by_public_key(self, public_key: str) -> ChatbotRow | None:
        """Look up a chatbot by its widget public key.

        Returns None if not found. Does NOT filter by tenant — the caller
        derives the tenant from the row's `tenant_id` afterwards (plan #16
        public chat endpoint uses this to bootstrap a tenant-scoped session).
        """
        from sqlalchemy import select

        stmt = select(ChatbotRow).where(
            ChatbotRow.public_key == public_key
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
```

If `select` is already imported at the top of the file, drop the `from sqlalchemy import select` inside the method.

### Step 2.4: Smoke-test the ORM and migration

Verify that the ORM model imports cleanly:

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
python -c "
from tfm_rag.infrastructure.persistence.models.chatbots import ChatbotRow
print('public_key column:', ChatbotRow.__table__.columns['public_key'].type)
print('nullable:', ChatbotRow.__table__.columns['public_key'].nullable)
"
```

Expected: prints `VARCHAR(64)` + `False`.

Then dry-run the migration (against the live Docker postgres):

```bash
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
alembic upgrade head 2>&1 | tail -15
```

Expected: applies migration `0009` (or whatever ID you used). No errors.

Confirm the column exists:

```bash
docker.exe exec tfm-rag-postgres-1 psql -U tfm -d tfm_rag -c "\\d chatbots" | grep -i public_key
```

Expected: a row with `public_key | character varying(64) | not null`.

### Step 2.5: Commit

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/alembic/versions/0009_chatbots_public_key.py \
        backend/src/tfm_rag/infrastructure/persistence/models/chatbots.py \
        backend/src/tfm_rag/infrastructure/persistence/repositories/chatbots_repo.py
git commit -m "feat(persistence): chatbots.public_key column + migration 0009 + get_by_public_key repo method (plan #11 Task 2)"
```

---

## Task 3 — Application: use cases handle public_key + WidgetConfig

**Files:**
- Modify: `backend/src/tfm_rag/domain/entities/chatbot.py`
- Modify: `backend/src/tfm_rag/application/chatbot_config/create_chatbot.py`
- Modify: `backend/src/tfm_rag/application/chatbot_config/update_chatbot.py`
- Modify: `backend/src/tfm_rag/application/chatbot_config/get_chatbot.py`
- Modify: `backend/src/tfm_rag/application/chatbot_config/list_chatbots.py`
- Modify: `backend/tests/unit/test_chatbot_use_cases.py`

### Step 3.1: Update the `Chatbot` domain entity

Open `backend/src/tfm_rag/domain/entities/chatbot.py`. Replace the field declaration:

```python
# Before:
widget_config: dict[str, Any]
```

with:

```python
widget_config: WidgetConfig
public_key: str
```

Add this import near the top of the file:

```python
from tfm_rag.domain.value_objects.widget_config import WidgetConfig
```

If `dict[str, Any]` is no longer needed (i.e. no other field uses it), remove the `from typing import Any` import.

### Step 3.2: Update `create_chatbot`

Open `backend/src/tfm_rag/application/chatbot_config/create_chatbot.py`. Make THREE changes:

**(a)** Add a public-key generator at module top (after imports):

```python
import secrets


def _generate_public_key() -> str:
    """Generate a widget public key: `wgt_` + 32 url-safe chars.

    No need for crypto-strength uniqueness — the unique constraint
    catches collisions. 32 chars of base64 = ~192 bits of entropy.
    """
    return "wgt_" + secrets.token_urlsafe(32)
```

**(b)** Change the function signature: the `widget_config` parameter becomes `WidgetConfig`:

```python
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
    widget_config: WidgetConfig,
) -> ChatbotView:
```

Add the import:

```python
from tfm_rag.domain.value_objects.widget_config import WidgetConfig
```

**(c)** In the body, generate the public_key and persist `widget_config.to_dict()`:

```python
    public_key = _generate_public_key()
    row = ChatbotRow(
        id=chatbot_id,
        tenant_id=ctx.tenant_id,
        name=name,
        description=description,
        system_prompt=system_prompt,
        llm_selection=llm_selection.to_dict(),
        pipeline_config=pipeline_config.to_dict(),
        widget_config=widget_config.to_dict(),
        public_key=public_key,
    )
```

**(d)** Update the `_to_view` helper (likely at the bottom of the file) to surface `widget_config` and `public_key` in the returned view. The view dataclass `ChatbotView` should already include `widget_config: dict[str, Any]` — if so, leave it as `widget_config.to_dict()`. If you want stronger typing, also add `widget_config: WidgetConfig` to the view, but that's a wider refactor — keep it as a dict in the view to minimise blast radius.

In particular, ensure the returned view includes `public_key=row.public_key`.

### Step 3.3: Update `update_chatbot`

Open `backend/src/tfm_rag/application/chatbot_config/update_chatbot.py`. Two changes:

**(a)** Signature: `widget_config: WidgetConfig | None`:

```python
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
    widget_config: WidgetConfig | None,
) -> ChatbotView:
```

Add the import:

```python
from tfm_rag.domain.value_objects.widget_config import WidgetConfig
```

**(b)** Body: persist `widget_config.to_dict()` instead of the raw dict, and DO NOT modify `public_key`:

```python
    if widget_config is not None:
        row.widget_config = widget_config.to_dict()
    # NOTE: public_key is intentionally NOT updateable via PATCH.
```

**(c)** Make sure `_to_view(row, kb_ids)` returns the row's `public_key` unchanged.

### Step 3.4: Update `get_chatbot` and `list_chatbots`

Both currently return a `ChatbotView` built from a `ChatbotRow`. Update `_to_view` (likely shared via a helper or duplicated across files) so it returns:

- `widget_config=row.widget_config` (still a dict — view layer stays loose; the API router will reconstruct the VO if needed for output)
- `public_key=row.public_key` (new field on the view)

Open the file containing `ChatbotView` (likely `application/chatbot_config/views.py` or inline at the bottom of each use case). Add a `public_key: str` field on `ChatbotView`.

### Step 3.5: Update unit tests

Open `backend/tests/unit/test_chatbot_use_cases.py`. Replace any literal:

```python
widget_config={"theme": "light"}
```

with the typed VO:

```python
from tfm_rag.domain.value_objects.widget_config import WidgetConfig
# ...
widget_config=WidgetConfig.default()
```

Add at least ONE new test that asserts `public_key` is generated on create and is a non-empty string starting with `"wgt_"`:

```python
async def test_create_chatbot_generates_public_key() -> None:
    # ... arrange fakes ...
    view = await create_chatbot(
        # ... existing kwargs ...
        widget_config=WidgetConfig.default(),
    )
    assert isinstance(view.public_key, str)
    assert view.public_key.startswith("wgt_")
    assert len(view.public_key) > 10
```

Add at least ONE test that asserts `update_chatbot` does NOT touch `public_key` (call update with no `widget_config`/with one, and assert the row's public_key was not assigned to).

### Step 3.6: Run the unit tests

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
pytest tests/unit/test_chatbot_use_cases.py -v 2>&1 | tail -25
```

Expected: existing tests + the new public_key tests all pass.

### Step 3.7: Commit

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/domain/entities/chatbot.py \
        backend/src/tfm_rag/application/chatbot_config/create_chatbot.py \
        backend/src/tfm_rag/application/chatbot_config/update_chatbot.py \
        backend/src/tfm_rag/application/chatbot_config/get_chatbot.py \
        backend/src/tfm_rag/application/chatbot_config/list_chatbots.py \
        backend/tests/unit/test_chatbot_use_cases.py
# Add views.py if exists:
# git add backend/src/tfm_rag/application/chatbot_config/views.py
git commit -m "feat(app): chatbot use cases — typed WidgetConfig + auto-generate public_key on create (plan #11 Task 3)"
```

---

## Task 4 — API: structured Pydantic models + public_key surface

**Files:**
- Modify: `backend/src/tfm_rag/infrastructure/api/routers/chatbots.py`
- Modify: `backend/tests/integration/test_chatbot_endpoints.py`

### Step 4.1: Add structured Pydantic models

Open `backend/src/tfm_rag/infrastructure/api/routers/chatbots.py`. Find the existing `CreateChatbotIn`, `UpdateChatbotIn`, `ChatbotOut` models.

Add this new model ABOVE them:

```python
class WidgetConfigIn(BaseModel):
    theme: Literal["light", "dark"] = "light"
    primary_color: str = "#3b82f6"
    position: Literal["bottom-right", "bottom-left"] = "bottom-right"
    title: str = Field(default="Asistente", min_length=1, max_length=60)
    welcome_message: str = Field(
        default="¿En qué puedo ayudarte?", min_length=1, max_length=500
    )
    placeholder: str = Field(
        default="Escribe tu pregunta...", min_length=1, max_length=100
    )
    allowed_origins: list[str] = Field(default_factory=list, max_length=50)

    def to_domain(self) -> "WidgetConfig":
        from tfm_rag.domain.value_objects.widget_config import WidgetConfig
        return WidgetConfig.from_dict(self.model_dump())


class WidgetConfigOut(BaseModel):
    theme: str
    primary_color: str
    position: str
    title: str
    welcome_message: str
    placeholder: str
    allowed_origins: list[str]

    @classmethod
    def from_domain(cls, raw: dict[str, Any]) -> "WidgetConfigOut":
        from tfm_rag.domain.value_objects.widget_config import WidgetConfig
        # Use VO's tolerant from_dict so legacy partial rows still work.
        vo = WidgetConfig.from_dict(raw or {})
        return cls(**vo.to_dict())
```

You need `from typing import Literal` and `from pydantic import Field` at the top — likely already imported.

Replace the existing `widget_config: dict[str, Any]` in `CreateChatbotIn`:

```python
class CreateChatbotIn(BaseModel):
    name: str
    description: str | None = None
    system_prompt: str
    llm_selection: LLMSelectionIn
    kb_ids: list[UUID] = Field(default_factory=list)
    pipeline_config: PipelineConfigIn = Field(default_factory=PipelineConfigIn)
    widget_config: WidgetConfigIn = Field(default_factory=WidgetConfigIn)
```

Replace in `UpdateChatbotIn`:

```python
class UpdateChatbotIn(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    llm_selection: LLMSelectionIn | None = None
    kb_ids: list[UUID] | None = None
    pipeline_config: PipelineConfigIn | None = None
    widget_config: WidgetConfigIn | None = None
```

Add `public_key` to `ChatbotOut`:

```python
class ChatbotOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: str | None
    system_prompt: str
    llm_selection: dict[str, Any]
    pipeline_config: dict[str, Any]
    widget_config: WidgetConfigOut
    kb_ids: list[str]
    public_key: str
```

### Step 4.2: Wire the conversions in the route handlers

Find the `create_` route. Where it currently calls `create_chatbot(..., widget_config=body.widget_config, ...)`, change to `widget_config=body.widget_config.to_domain()`.

Find the `patch_` route. Where it calls `update_chatbot(..., widget_config=body.widget_config, ...)`, change to:

```python
widget_config=body.widget_config.to_domain() if body.widget_config is not None else None,
```

Find the construction of `ChatbotOut` from the view (in `get_`, `list_`, `create_`, `patch_`). Where it currently sets `widget_config=view.widget_config`, change to `widget_config=WidgetConfigOut.from_domain(view.widget_config)`, and add `public_key=view.public_key`.

### Step 4.3: Update integration tests

Open `backend/tests/integration/test_chatbot_endpoints.py`. Find any literal `"widget_config": {"theme": "light"}` in test bodies. The new shape is fine — it'll be merged with defaults. The endpoint should still return 201.

Add a new test that exercises the public_key being:
- generated on create
- returned in the response
- the same on subsequent GETs
- NOT changed by a PATCH that doesn't include public_key (PATCH ignores it even if sent)

Append to the file:

```python
async def test_public_key_generated_and_immutable(_clean_state: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # ... reuse _register helper and create chatbot ...
        # Assert response includes a public_key starting with "wgt_".
        # GET the chatbot → assert same public_key.
        # PATCH with a different "public_key" in the body → server should
        # reject the extra field (Pydantic strict by default) OR ignore it;
        # afterwards the public_key on the row must be unchanged.
```

Write it concretely using the same fixtures the existing tests use. If you don't have local access to the fixture names, GREP first:

```bash
grep -n "async def _register\|_register_and_create_chatbot\|_clean_state" backend/tests/integration/test_chatbot_endpoints.py | head
```

Then mirror the existing pattern.

A skeleton (adjust to match the file's fixtures):

```python
async def test_public_key_generated_and_immutable(_clean_state: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token = await _register(c, "widget-test@example.com")
        h = {"Authorization": f"Bearer {token}"}
        # create chatbot (reuse the helper if present, else build inline):
        creds = (await c.get("/api/credentials", headers=h)).json()
        cred_id = next(cr for cr in creds if cr["provider_id"] == "ollama")["id"]
        r = await c.post("/api/chatbots", headers=h, json={
            "name": "T1",
            "system_prompt": "be brief",
            "llm_selection": {
                "provider_id": "ollama", "credential_id": cred_id,
                "model_id": "llama3.1",
            },
            "kb_ids": [],
            "pipeline_config": {"top_k": 3, "max_retrieval_iterations": 3},
        })
        assert r.status_code == 201, r.text
        chatbot_id = r.json()["id"]
        public_key = r.json()["public_key"]
        assert public_key.startswith("wgt_")

        # GET returns same public_key
        r2 = await c.get(f"/api/chatbots/{chatbot_id}", headers=h)
        assert r2.json()["public_key"] == public_key

        # PATCH with a different public_key in the body is either rejected
        # (422) or silently ignored — either way, public_key must NOT change.
        r3 = await c.patch(
            f"/api/chatbots/{chatbot_id}", headers=h,
            json={"public_key": "wgt_attacker"},
        )
        # Re-read the chatbot:
        r4 = await c.get(f"/api/chatbots/{chatbot_id}", headers=h)
        assert r4.json()["public_key"] == public_key
```

If Pydantic strict mode is ON for `UpdateChatbotIn`, the PATCH with `{"public_key": ...}` returns 422 (extra field). If it's OFF, it returns 200 but the value is ignored. Either way the post-check passes. Don't set Pydantic strict mode — leave the model's default.

### Step 4.4: Run the integration tests

Reset the chatbots schema if needed (after Task 2's migration, the existing chatbots rows have been backfilled with public_keys; new tests truncate anyway):

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
pytest tests/integration/test_chatbot_endpoints.py -m integration -v --timeout=180 2>&1 | tail -25
```

Expected: existing tests + new `test_public_key_generated_and_immutable` all pass.

### Step 4.5: Commit

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/infrastructure/api/routers/chatbots.py \
        backend/tests/integration/test_chatbot_endpoints.py
git commit -m "feat(api): structured WidgetConfigIn/Out + public_key in ChatbotOut + immutability test (plan #11 Task 4)"
```

---

## Task 5 — get_chatbot_by_public_key helper + CORS middleware

**Files:**
- Create: `backend/src/tfm_rag/application/chatbot_config/get_chatbot_by_public_key.py`
- Modify: `backend/src/tfm_rag/infrastructure/api/app.py`
- Create: `backend/tests/unit/test_get_chatbot_by_public_key.py`
- Create: `backend/tests/integration/test_chatbot_widget_config_endpoints.py`

### Step 5.1: Write the failing unit test

Create `backend/tests/unit/test_get_chatbot_by_public_key.py`:

```python
"""Unit tests for get_chatbot_by_public_key (tenant-agnostic lookup)."""
from typing import Any
from uuid import UUID, uuid4

import pytest

from tfm_rag.application.chatbot_config.get_chatbot_by_public_key import (
    PublicKeyNotFoundError,
    get_chatbot_by_public_key,
)

pytestmark = pytest.mark.asyncio


class _FakeRow:
    def __init__(self, *, tenant_id: UUID, public_key: str) -> None:
        self.id = uuid4()
        self.tenant_id = tenant_id
        self.name = "EmbedBot"
        self.description = None
        self.system_prompt = "be helpful"
        self.llm_selection = {
            "provider_id": "ollama", "credential_id": str(uuid4()),
            "model_id": "llama3.1",
        }
        self.pipeline_config = {"top_k": 3, "max_retrieval_iterations": 3}
        self.widget_config = {"theme": "light"}
        self.public_key = public_key
        self.kb_ids: list[UUID] = []


class _FakeChatbotRepo:
    def __init__(self, rows: dict[str, _FakeRow]) -> None:
        self._rows = rows

    async def get_by_public_key(self, public_key: str) -> _FakeRow | None:
        return self._rows.get(public_key)


class _FakeSession:
    pass


async def test_returns_view_when_key_exists() -> None:
    tenant_id = uuid4()
    row = _FakeRow(tenant_id=tenant_id, public_key="wgt_real")
    repo = _FakeChatbotRepo({"wgt_real": row})

    view = await get_chatbot_by_public_key(
        session=_FakeSession(),  # type: ignore[arg-type]
        public_key="wgt_real",
        chatbot_repo=repo,  # type: ignore[arg-type]
    )

    assert view.id == row.id
    assert view.tenant_id == tenant_id
    assert view.public_key == "wgt_real"
    # widget_config returns a dict (the API layer reshapes it)
    assert view.widget_config == {"theme": "light"}


async def test_raises_when_key_missing() -> None:
    repo = _FakeChatbotRepo({})
    with pytest.raises(PublicKeyNotFoundError) as exc_info:
        await get_chatbot_by_public_key(
            session=_FakeSession(),  # type: ignore[arg-type]
            public_key="wgt_bogus",
            chatbot_repo=repo,  # type: ignore[arg-type]
        )
    # Error message MUST NOT echo the supplied key (defence vs enumeration).
    assert "wgt_bogus" not in str(exc_info.value)


async def test_does_not_filter_by_tenant() -> None:
    """The use case is intentionally tenant-agnostic — the caller derives
    the tenant from the loaded row. Verify by 'creating' a row from one
    tenant and looking it up via the public_key alone (no ctx)."""
    tenant_id = uuid4()
    row = _FakeRow(tenant_id=tenant_id, public_key="wgt_cross")
    repo = _FakeChatbotRepo({"wgt_cross": row})

    view = await get_chatbot_by_public_key(
        session=_FakeSession(),  # type: ignore[arg-type]
        public_key="wgt_cross",
        chatbot_repo=repo,  # type: ignore[arg-type]
    )
    assert view.tenant_id == tenant_id
```

### Step 5.2: Implement the use case

Create `backend/src/tfm_rag/application/chatbot_config/get_chatbot_by_public_key.py`:

```python
"""get_chatbot_by_public_key — tenant-agnostic chatbot lookup for plan #16.

The widget public chat endpoint has no JWT (no tenant context). It
identifies the bot purely by the URL-embedded `public_key`. This use case
loads the chatbot row by public_key, returning a `ChatbotView` that
includes `tenant_id` so the caller can build a RequestContext for
downstream tenant-scoped queries (sessions, retrieval, etc.).

NO tenant filter is applied; the public_key is the security token here.
The unique constraint on `chatbots.public_key` guarantees ≤1 match.
"""
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.common import DomainError


class PublicKeyNotFoundError(DomainError):
    """Raised when no chatbot row matches the supplied public_key.

    The error message intentionally does NOT include the supplied key —
    that would aid enumeration attacks.
    """


@dataclass(frozen=True, slots=True)
class PublicKeyChatbotView:
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    system_prompt: str
    llm_selection: dict[str, Any]
    pipeline_config: dict[str, Any]
    widget_config: dict[str, Any]
    public_key: str
    kb_ids: list[UUID]


class _ChatbotRepoLike(Protocol):
    async def get_by_public_key(self, public_key: str) -> Any: ...


async def get_chatbot_by_public_key(
    *,
    session: AsyncSession,
    public_key: str,
    chatbot_repo: _ChatbotRepoLike,
) -> PublicKeyChatbotView:
    row = await chatbot_repo.get_by_public_key(public_key)
    if row is None:
        raise PublicKeyNotFoundError("chatbot not found")

    # kb_ids on the row may be a lazy relationship; if the repo populates
    # it (some implementations do), we use it. Otherwise default to [].
    kb_ids = list(getattr(row, "kb_ids", []) or [])

    return PublicKeyChatbotView(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        description=row.description,
        system_prompt=row.system_prompt,
        llm_selection=dict(row.llm_selection or {}),
        pipeline_config=dict(row.pipeline_config or {}),
        widget_config=dict(row.widget_config or {}),
        public_key=row.public_key,
        kb_ids=kb_ids,
    )
```

### Step 5.3: Run the unit test

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
pytest tests/unit/test_get_chatbot_by_public_key.py -v 2>&1 | tail -15
```

Expected: **3 passed**.

### Step 5.4: Add CORS middleware

Open `backend/src/tfm_rag/infrastructure/api/app.py`. Add CORS middleware AFTER the existing `TenantScopingMiddleware`:

```python
from fastapi.middleware.cors import CORSMiddleware
```

In `create_app()`:

```python
    app = FastAPI(
        title="TFM RAG Chatbot Platform",
        version="0.1.0",
    )
    settings = get_settings()
    app.add_middleware(TenantScopingMiddleware, settings=settings)
    # Plan #16 will tighten this to per-chatbot allowed_origins (in the
    # widget public endpoint, the chatbot's allowed_origins list narrows
    # the response). Plan #11 ships permissive defaults so the embeddable
    # widget can prototype against a dev backend.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

`allow_credentials=False` is required when `allow_origins=["*"]` (browser security rule). Plan #16 will set it explicitly to True when narrowing per-chatbot allowed origins.

### Step 5.5: Write the integration test for CORS + helper smoke

Create `backend/tests/integration/test_chatbot_widget_config_endpoints.py`:

```python
"""Integration tests for widget config + public_key + CORS scaffolding."""
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

pytestmark = pytest.mark.integration


@pytest.fixture
async def _clean_state(settings: Settings) -> None:
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    async with factory() as s:
        await s.execute(text(
            "TRUNCATE chat_messages, chat_sessions, "
            "chatbot_knowledge_base, chatbots, "
            "sources, knowledge_bases, provider_credentials, "
            "users, tenants RESTART IDENTITY CASCADE"
        ))
        await s.commit()
    await engine.dispose()
    _deps._session_factory = None


async def _register_and_make_chatbot(c: AsyncClient) -> dict:
    r = await c.post(
        "/api/auth/register",
        json={"email": "widget-cfg@example.com", "password": "correctpassword"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    creds = (await c.get("/api/credentials", headers=h)).json()
    cred_id = next(cr for cr in creds if cr["provider_id"] == "ollama")["id"]
    r = await c.post(
        "/api/chatbots", headers=h,
        json={
            "name": "WidgetBot",
            "system_prompt": "be brief",
            "llm_selection": {
                "provider_id": "ollama", "credential_id": cred_id,
                "model_id": "llama3.1",
            },
            "kb_ids": [],
            "pipeline_config": {"top_k": 3, "max_retrieval_iterations": 3},
            "widget_config": {
                "theme": "dark",
                "primary_color": "#10b981",
                "title": "Asistente WidgetBot",
                "allowed_origins": ["https://acme.example.com"],
            },
        },
    )
    assert r.status_code == 201, r.text
    return {"token": token, "body": r.json()}


async def test_create_chatbot_structured_widget_config_round_trips(
    _clean_state: None,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        info = await _register_and_make_chatbot(c)
        body = info["body"]
        assert body["widget_config"]["theme"] == "dark"
        assert body["widget_config"]["primary_color"] == "#10b981"
        assert body["widget_config"]["title"] == "Asistente WidgetBot"
        assert body["widget_config"]["allowed_origins"] == [
            "https://acme.example.com"
        ]
        # defaults filled in:
        assert body["widget_config"]["position"] == "bottom-right"
        assert body["widget_config"]["welcome_message"]
        assert body["widget_config"]["placeholder"]

        # public_key generated
        assert body["public_key"].startswith("wgt_")


async def test_widget_config_validation_rejects_bad_color(
    _clean_state: None,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/auth/register",
            json={"email": "w2@example.com", "password": "correctpassword"},
        )
        token = r.json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        creds = (await c.get("/api/credentials", headers=h)).json()
        cred_id = next(cr for cr in creds if cr["provider_id"] == "ollama")["id"]

        # Bad hex color → 422 (Pydantic regex) OR 400 (domain validation).
        r = await c.post(
            "/api/chatbots", headers=h,
            json={
                "name": "Bad", "system_prompt": "p",
                "llm_selection": {
                    "provider_id": "ollama", "credential_id": cred_id,
                    "model_id": "llama3.1",
                },
                "kb_ids": [],
                "pipeline_config": {"top_k": 3, "max_retrieval_iterations": 3},
                "widget_config": {"primary_color": "blue"},
            },
        )
        assert r.status_code in (400, 422)


async def test_cors_preflight_allowed_for_public_paths(
    _clean_state: None,
) -> None:
    """A browser preflight from any origin to /api/public/anything must
    return 200 with CORS headers (plan #16 will narrow per chatbot)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.request(
            "OPTIONS", "/api/public/foo",
            headers={
                "Origin": "https://acme.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        # FastAPI's CORSMiddleware returns 200 with appropriate headers
        # for preflight. The exact status code is not the only signal —
        # the header `Access-Control-Allow-Origin` MUST be present.
        assert "access-control-allow-origin" in {
            k.lower() for k in r.headers
        }
```

### Step 5.6: Run the integration test

```bash
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
pytest tests/integration/test_chatbot_widget_config_endpoints.py -m integration -v --timeout=180 2>&1 | tail -25
```

Expected: **3 passed**.

### Step 5.7: Run the full integration suite (regression check)

```bash
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
pytest tests/integration -m integration --timeout=900 2>&1 | tail -10
```

Expected: previous (37 passed + 1 flake) + 1 new endpoint test from Task 4 + 3 new from Task 5 = **41 PASSED / 42 total**.

### Step 5.8: Commit + tag

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/application/chatbot_config/get_chatbot_by_public_key.py \
        backend/src/tfm_rag/infrastructure/api/app.py \
        backend/tests/unit/test_get_chatbot_by_public_key.py \
        backend/tests/integration/test_chatbot_widget_config_endpoints.py
git commit -m "feat(api): get_chatbot_by_public_key + CORS middleware (permissive) — plan #11 Task 5"
git tag cap-11-chatbot-widget-config
```

---

## Controller cleanup (post-subagent — NOT a task)

After all 5 tasks land:

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
ruff check . --fix
mypy src/
pytest tests/ -m "not integration"
```

If autofixes / type fixes are applied:

```bash
git add <files>
git commit -m "chore(plan-11): ruff autofix + mypy fix"
git tag -f cap-11-chatbot-widget-config <cleanup-commit-sha>
```

---

## What's next after plan #11

After plan #11 lands, **only plan #16 (WIDGET-RUNTIME, M5) remains**: the embeddable JS widget + the `POST /api/public/chatbots/{public_key}/chat` endpoint that uses `get_chatbot_by_public_key` shipped in this plan.

Small follow-ups that pair well with plan #11:
- **Per-chatbot CORS narrowing** — in plan #16's public endpoint, the response headers should set `Access-Control-Allow-Origin` based on the chatbot's `widget_config.allowed_origins` (instead of the permissive `*`). This is enforced at the application layer because CORS middleware is global.
- **Rotate public_key** — an `Action: rotate` button on the panel + a `POST /api/chatbots/{id}/rotate-public-key` endpoint. Useful when a key leaks.
- **Public_key prefix taxonomy** — `wgt_` is the only prefix today; later we might add `srv_` for server-to-server keys, `pub_` for read-only keys, etc.
