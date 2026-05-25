# CAP-WIDGET-RUNTIME Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the embeddable chat widget. Adds the **public** chat endpoint (`POST /api/public/chatbots/{public_key}/chat` + `GET /api/public/chatbots/{public_key}/config`) and a self-contained **vanilla-JS widget** (`/widget/widget.js`) that any external site can embed via `<script src="...">`.

**Architecture:** Two new backend routes living in a new `public_chat` router. Both resolve the chatbot via the plan-#11 helper `get_chatbot_by_public_key` and build a `RequestContext(tenant_id=row.tenant_id, user_id=None)` to call the existing `answer_query` use case. Session continuity for anonymous users is handled via a `public_session_cookie` (random opaque string the widget generates client-side and persists in `localStorage`); the server verifies cookie+session_id agree on every follow-up turn (defence against session hijacking). Per-chatbot CORS narrowing is done in the application layer (the response sets `Access-Control-Allow-Origin` from `widget_config.allowed_origins`, falling back to "do not allow" if `Origin` doesn't match any allowed entry). The widget JS is a single ~400-line vanilla file rendered into a Shadow DOM so its CSS can't be polluted by the host page.

**Tech Stack:** Python 3.12, FastAPI, FastAPI `StaticFiles`, asyncpg/asyncmy already present from plans #9-13, vanilla JavaScript ES2022, Shadow DOM, `fetch()` API, pytest + pytest-asyncio.

---

## File structure

**New files:**

- `backend/src/tfm_rag/infrastructure/api/routers/public_chat.py` — public router with the 2 endpoints + the CORS helper.
- `backend/src/tfm_rag/application/chat/widget_cors.py` — per-chatbot CORS resolver (`resolve_allowed_origin(origin, allowed_origins) -> str | None`).
- `widget/widget.js` — embeddable widget (single file).
- `widget/index.html` — local demo page for manual testing (NOT served in production; under `widget/` for dev convenience).
- `backend/tests/unit/test_widget_cors.py`
- `backend/tests/integration/test_public_widget_endpoints.py`

**Modified files:**

- `backend/src/tfm_rag/infrastructure/api/app.py` — mount `StaticFiles` at `/widget` + include the new public router.
- `backend/src/tfm_rag/application/chat/answer_query.py` — accept optional `session_origin: Literal["playground","widget"]` + `public_session_cookie: str | None` kwargs to forward to `create_session`. Today the call always uses `origin="playground", public_session_cookie=None`. **NB**: this is a 2-line change; existing callers keep working because defaults preserve old behavior.

**Out of scope** (deferred):

- A full panel UI for the snippet copy + live preview (the snippet is documented in this plan; the admin panel UI will follow as a separate frontend ticket).
- Rate limiting on the public endpoint (acceptable for a demo; add `slowapi` or similar in production).
- WebSocket streaming of LLM tokens (the endpoint is one-shot JSON).
- Custom domain support for the widget (it always loads from the deploy's own host).
- Multi-language widget UI (Spanish strings only for MVP — the panel can later supply localized copy via `widget_config`).
- Markdown rendering inside assistant bubbles (we render the answer as plain text). Citations are NOT shown in the widget (they exist in the API response; UI is doc-only follow-up).

---

## Task 1 — Public router: config + per-chatbot CORS resolver

**Files:**
- Create: `backend/src/tfm_rag/application/chat/widget_cors.py`
- Create: `backend/src/tfm_rag/infrastructure/api/routers/public_chat.py` (initial — config endpoint only; chat endpoint lands in Task 2)
- Modify: `backend/src/tfm_rag/infrastructure/api/app.py` (include the new router)
- Create: `backend/tests/unit/test_widget_cors.py`

### Step 1.1: Write the failing test for the CORS resolver

Create `backend/tests/unit/test_widget_cors.py`:

```python
"""Unit tests for the per-chatbot CORS resolver."""
import pytest

from tfm_rag.application.chat.widget_cors import resolve_allowed_origin


# --- empty allowed list -------------------------------------------------------


def test_empty_allowed_origins_allows_any_request_origin() -> None:
    # The chatbot owner didn't restrict origins; default permissive.
    assert (
        resolve_allowed_origin(
            request_origin="https://acme.example.com",
            allowed_origins=(),
        )
        == "https://acme.example.com"
    )


def test_empty_allowed_origins_with_no_request_origin_returns_none() -> None:
    # No Origin header sent (probably curl / server-to-server); no CORS header.
    assert (
        resolve_allowed_origin(
            request_origin=None,
            allowed_origins=(),
        )
        is None
    )


# --- wildcard -----------------------------------------------------------------


def test_wildcard_with_request_origin_echoes_request_origin() -> None:
    # We MUST NOT return literal "*" when allow_credentials may be true.
    # The widget always echoes the actual origin instead of "*".
    assert (
        resolve_allowed_origin(
            request_origin="https://anything.test",
            allowed_origins=("*",),
        )
        == "https://anything.test"
    )


def test_wildcard_with_no_request_origin_returns_none() -> None:
    assert (
        resolve_allowed_origin(
            request_origin=None,
            allowed_origins=("*",),
        )
        is None
    )


# --- explicit list ------------------------------------------------------------


def test_origin_in_explicit_list_is_echoed() -> None:
    assert (
        resolve_allowed_origin(
            request_origin="https://acme.example.com",
            allowed_origins=(
                "https://acme.example.com",
                "https://other.example.com",
            ),
        )
        == "https://acme.example.com"
    )


def test_origin_not_in_explicit_list_returns_none() -> None:
    assert (
        resolve_allowed_origin(
            request_origin="https://attacker.example.com",
            allowed_origins=(
                "https://acme.example.com",
                "https://other.example.com",
            ),
        )
        is None
    )


def test_case_sensitive_match() -> None:
    # Origins are case-sensitive at the host level (well-known web behavior).
    # We do NOT canonicalize.
    assert (
        resolve_allowed_origin(
            request_origin="https://Acme.example.com",
            allowed_origins=("https://acme.example.com",),
        )
        is None
    )


def test_port_must_match_exactly() -> None:
    assert (
        resolve_allowed_origin(
            request_origin="http://localhost:3000",
            allowed_origins=("http://localhost:8080",),
        )
        is None
    )
    assert (
        resolve_allowed_origin(
            request_origin="http://localhost:3000",
            allowed_origins=("http://localhost:3000",),
        )
        == "http://localhost:3000"
    )


def test_scheme_must_match_exactly() -> None:
    assert (
        resolve_allowed_origin(
            request_origin="http://acme.example.com",
            allowed_origins=("https://acme.example.com",),
        )
        is None
    )


def test_no_request_origin_with_explicit_list_returns_none() -> None:
    # Server-to-server (no Origin header) is allowed at the application
    # layer regardless of the list — we just don't emit a CORS header.
    assert (
        resolve_allowed_origin(
            request_origin=None,
            allowed_origins=("https://acme.example.com",),
        )
        is None
    )
```

Run the test (expect ImportError):

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
pytest tests/unit/test_widget_cors.py -v 2>&1 | tail -15
```

### Step 1.2: Implement the resolver

Create `backend/src/tfm_rag/application/chat/widget_cors.py`:

```python
"""Per-chatbot CORS resolver for the widget public endpoints.

The global CORSMiddleware (plan #11) is permissive (`*`, no credentials).
That makes the preflight succeed for any origin so the widget can call
the public endpoints; but for the ACTUAL response, we want to NARROW the
`Access-Control-Allow-Origin` to what the chatbot owner declared in
`widget_config.allowed_origins`. This module implements that decision.

Returned value is what the route sets in the `Access-Control-Allow-Origin`
response header. None means "no header" — i.e. the browser will block
the request from being read by the embedding page.

We intentionally never return literal `"*"`; if the user-declared list is
`("*",)`, we echo back the actual request `Origin`. This is necessary
when `allow_credentials=true` (browser security rule) and also gives
better diagnostics (the response shows exactly which origin was allowed).
"""

def resolve_allowed_origin(
    *, request_origin: str | None, allowed_origins: tuple[str, ...] | list[str],
) -> str | None:
    """Return the value to set in `Access-Control-Allow-Origin`, or None.

    Rules:
      * No `Origin` header in the request → return None.
      * `allowed_origins` is empty (owner didn't restrict) → echo request_origin.
      * `*` is in the list → echo request_origin.
      * request_origin matches an entry exactly (case-sensitive, port/scheme
        included) → echo request_origin.
      * Otherwise → None.
    """
    if request_origin is None:
        return None
    allowed_tuple = tuple(allowed_origins)
    if not allowed_tuple:
        return request_origin
    if "*" in allowed_tuple:
        return request_origin
    if request_origin in allowed_tuple:
        return request_origin
    return None
```

### Step 1.3: Run the resolver tests

```bash
pytest tests/unit/test_widget_cors.py -v 2>&1 | tail -15
```

Expected: **10 passed**.

### Step 1.4: Create the public router (config endpoint only)

Create `backend/src/tfm_rag/infrastructure/api/routers/public_chat.py`:

```python
"""Public widget endpoints — no JWT, identified by chatbot.public_key.

Routes:
  - GET  /api/public/chatbots/{public_key}/config
  - POST /api/public/chatbots/{public_key}/chat  (Task 2 of plan #16)

The TenantScopingMiddleware lets `/api/public/*` through without parsing
a JWT (and sets request.state.ctx = None). Each route MUST derive the
tenant from the resolved chatbot row and build its own RequestContext.

The global CORSMiddleware is permissive (`*`, no credentials) so the
browser preflight succeeds. The actual response header is set per-chatbot
via `resolve_allowed_origin` (see `application/chat/widget_cors.py`).
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.chat.widget_cors import resolve_allowed_origin
from tfm_rag.application.chatbot_config.get_chatbot_by_public_key import (
    PublicKeyChatbotView,
    PublicKeyNotFoundError,
    get_chatbot_by_public_key,
)
from tfm_rag.domain.value_objects.widget_config import WidgetConfig
from tfm_rag.infrastructure.api.dependencies import get_session
from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
    ChatbotRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

router = APIRouter(prefix="/api/public/chatbots", tags=["public-widget"])


# --- helpers ------------------------------------------------------------------


async def _load_or_404(
    session: AsyncSession, public_key: str
) -> PublicKeyChatbotView:
    repo = ChatbotRepository(session, RequestContext(
        tenant_id=__import__("uuid").UUID(int=0),  # placeholder; the repo
        user_id=None,                              # method we use is tenant-agnostic
    ))
    try:
        return await get_chatbot_by_public_key(
            session=session,
            public_key=public_key,
            chatbot_repo=repo,
        )
    except PublicKeyNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _apply_cors(
    response: Response, request: Request, widget_cfg: WidgetConfig
) -> None:
    origin = request.headers.get("origin")
    allowed = resolve_allowed_origin(
        request_origin=origin, allowed_origins=widget_cfg.allowed_origins
    )
    if allowed is not None:
        response.headers["Access-Control-Allow-Origin"] = allowed
        # Allow credentials so the widget can later carry first-party cookies
        # if we ever add an alternative session backend. Vary on Origin so
        # caching is correct.
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"


# --- GET /config --------------------------------------------------------------


class PublicConfigOut(BaseModel):
    chatbot_id: str
    name: str
    widget: dict[str, Any]


@router.get("/{public_key}/config", response_model=PublicConfigOut)
async def widget_config_(
    public_key: str,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PublicConfigOut:
    view = await _load_or_404(session, public_key)
    widget_cfg = WidgetConfig.from_dict(view.widget_config)
    _apply_cors(response, request, widget_cfg)
    return PublicConfigOut(
        chatbot_id=str(view.id),
        name=view.name,
        widget=widget_cfg.to_dict(),
    )
```

The `_load_or_404` helper builds a `ChatbotRepository` with a placeholder tenant_id because `get_by_public_key` does NOT filter by tenant (plan #11 design — the public_key is the security token). If the repo's `__init__` requires `RequestContext`, the placeholder is fine; if it doesn't take ctx at all, drop the second arg.

(Some repo constructors take just `session`; others take `session, ctx`. The plan #11 task 2 step added `get_by_public_key` to the existing `ChatbotRepository` — look at the file to confirm the constructor shape. If it's `__init__(self, session)`, drop `RequestContext(...)`.)

### Step 1.5: Wire the router

Open `backend/src/tfm_rag/infrastructure/api/app.py`. Add the import next to the existing router imports:

```python
from tfm_rag.infrastructure.api.routers import (
    auth,
    chatbots,
    credentials,
    health,
    ingestion_jobs,
    knowledge_bases,
    public_chat,
    sessions,
)
```

And include it in `create_app()`:

```python
    app.include_router(public_chat.router)
```

### Step 1.6: Smoke-test the new endpoint

Restart-free: just hit it via httpx/pytest. Quick manual smoke:

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
python -c "
from tfm_rag.infrastructure.api.app import app
for route in app.routes:
    path = getattr(route, 'path', '?')
    if 'public' in path:
        print(path)
"
```

Expected: prints `/api/public/chatbots/{public_key}/config`.

### Step 1.7: Commit

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/application/chat/widget_cors.py \
        backend/src/tfm_rag/infrastructure/api/routers/public_chat.py \
        backend/src/tfm_rag/infrastructure/api/app.py \
        backend/tests/unit/test_widget_cors.py
git commit -m "feat(public): GET /api/public/chatbots/{public_key}/config + per-chatbot CORS resolver (plan #16 Task 1)"
```

---

## Task 2 — Public chat endpoint + session cookie verification

**Files:**
- Modify: `backend/src/tfm_rag/infrastructure/api/routers/public_chat.py` (append POST /chat handler)
- Modify: `backend/src/tfm_rag/application/chat/answer_query.py` (accept `session_origin` + `public_session_cookie` kwargs)
- Create: `backend/tests/unit/test_widget_session_cookie_verifier.py` (lightweight: just the cookie-mismatch path)

The chat endpoint:
1. Loads the chatbot by public_key (404 if missing).
2. Reads optional `session_id` from the request body and optional `X-Widget-Session-Cookie` header from the request.
3. If `session_id` is provided AND the cookie does not match the row's `public_session_cookie`, returns **403**.
4. If `session_id` is null, the request body's cookie value is forwarded to `create_session(origin="widget", public_session_cookie=cookie)`.
5. Builds a fresh `RequestContext(tenant_id=row.tenant_id, user_id=None)`.
6. Calls `answer_query` with the new `session_origin="widget"` + `public_session_cookie=cookie` kwargs (added to `answer_query` in this task).
7. Returns the same `ChatOut` shape as the authenticated endpoint.

### Step 2.1: Update `answer_query`

Open `backend/src/tfm_rag/application/chat/answer_query.py`. Find the line where it calls `create_session(...)` (the survey showed it at approximately line 234-239). Currently it's hardcoded to `origin="playground", public_session_cookie=None`.

Add two new keyword-only parameters to the `answer_query` function signature, defaulted to the current behavior:

```python
async def answer_query(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    # ... all existing kwargs ...
    # NEW (plan #16):
    session_origin: Literal["playground", "widget"] = "playground",
    public_session_cookie: str | None = None,
) -> AnswerView:
```

`Literal` is likely already imported. If not, add `from typing import Literal`.

Then change the `create_session` call to use those values:

```python
        if session_id is None:
            if persist:
                session_id = await create_session(
                    session, ctx,
                    chatbot_id=chatbot_id,
                    origin=session_origin,
                    public_session_cookie=public_session_cookie,
                )
```

If `answer_query` ALSO loads an existing session by id, no change is needed there — the cookie verification lives in the router for plan #16 (it has access to the loaded row).

### Step 2.2: Add a tiny cookie-verifier unit test

We don't have a unit-level cookie verifier function (verification is inline in the router for simplicity), so the unit test for cookie mismatch lives at the integration level (Task 3). However, add this **smoke unit test** for the function signature update on `answer_query`:

Create `backend/tests/unit/test_widget_session_cookie_verifier.py`:

```python
"""Smoke test for the new session_origin / public_session_cookie kwargs
on answer_query. Full behavior is covered in Task 3 integration tests."""
import inspect

from tfm_rag.application.chat.answer_query import answer_query


def test_answer_query_accepts_session_origin_kwarg() -> None:
    sig = inspect.signature(answer_query)
    assert "session_origin" in sig.parameters
    assert "public_session_cookie" in sig.parameters
    # Defaults preserve old behavior:
    assert sig.parameters["session_origin"].default == "playground"
    assert sig.parameters["public_session_cookie"].default is None
```

Run it:

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
pytest tests/unit/test_widget_session_cookie_verifier.py -v 2>&1 | tail -10
```

Expected: **1 passed**.

### Step 2.3: Add the public chat endpoint

Open `backend/src/tfm_rag/infrastructure/api/routers/public_chat.py`. Append at the end:

```python
# --- POST /chat ---------------------------------------------------------------

from uuid import UUID

from tfm_rag.application.chat.answer_query import answer_query
from tfm_rag.infrastructure.embedders.dispatcher import EmbedderDispatcher
from tfm_rag.infrastructure.llm_providers.dispatcher import LLMDispatcher
from tfm_rag.infrastructure.persistence.models.chat_sessions import (
    ChatSessionRow,
)
from tfm_rag.infrastructure.settings import Settings, get_settings
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore
from tfm_rag.infrastructure.api.routers.chatbots import ChatOut


class PublicChatIn(BaseModel):
    session_id: str | None = None
    public_session_cookie: str
    message: str


@router.post("/{public_key}/chat", response_model=ChatOut)
async def public_chat_(
    public_key: str,
    body: PublicChatIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> ChatOut:
    view = await _load_or_404(session, public_key)
    widget_cfg = WidgetConfig.from_dict(view.widget_config)
    _apply_cors(response, request, widget_cfg)

    # --- session_id + cookie verification ----------------------------------
    parsed_session_id: UUID | None = None
    if body.session_id:
        try:
            parsed_session_id = UUID(body.session_id)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"session_id is not a valid UUID: {body.session_id!r}",
            ) from exc

        # Verify cookie matches the persisted row.
        from sqlalchemy import select

        stmt = select(ChatSessionRow).where(
            ChatSessionRow.id == parsed_session_id,
            ChatSessionRow.chatbot_id == view.id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="session not found",
            )
        if row.origin != "widget":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="session origin mismatch (not a widget session)",
            )
        if row.public_session_cookie != body.public_session_cookie:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, detail="invalid session cookie",
            )

    # --- ctx for downstream tenant-scoped operations -----------------------
    ctx = RequestContext(tenant_id=view.tenant_id, user_id=None)

    qdrant = QdrantStore(settings.qdrant_url, settings.qdrant_api_key)
    try:
        result = await answer_query(
            session, ctx,
            llm_dispatcher=LLMDispatcher.default(),
            qdrant=qdrant,
            embedder_dispatcher=EmbedderDispatcher.default(),
            settings=settings,
            chatbot_id=view.id,
            session_id=parsed_session_id,
            user_message=body.message,
            session_origin="widget",
            public_session_cookie=body.public_session_cookie,
        )
    finally:
        await qdrant.close()

    return ChatOut.from_view(result)
```

The `ChatOut` import from `routers.chatbots` is intentional re-use of the authenticated endpoint's response model. If that creates an import cycle (because chatbots.py might import something from public_chat at some future point), break the cycle by lifting `ChatOut` into a shared `routers/_shared.py` instead. For now the cycle is one-way and safe.

### Step 2.4: Smoke-test imports

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
python -c "
from tfm_rag.infrastructure.api.app import app
public_routes = [
    (r.methods, r.path) for r in app.routes
    if hasattr(r, 'path') and 'public' in r.path
]
for methods, path in public_routes:
    print(sorted(methods), path)
"
```

Expected: prints both `GET /api/public/chatbots/{public_key}/config` and `POST /api/public/chatbots/{public_key}/chat`.

### Step 2.5: Run the unit test

```bash
pytest tests/unit/test_widget_session_cookie_verifier.py -v 2>&1 | tail -10
```

Expected: **1 passed**.

### Step 2.6: Commit

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/infrastructure/api/routers/public_chat.py \
        backend/src/tfm_rag/application/chat/answer_query.py \
        backend/tests/unit/test_widget_session_cookie_verifier.py
git commit -m "feat(public): POST /api/public/chatbots/{public_key}/chat + cookie-verified sessions (plan #16 Task 2)"
```

---

## Task 3 — Widget JS file + static serving

**Files:**
- Create: `widget/widget.js`
- Create: `widget/index.html` (manual demo page)
- Modify: `backend/src/tfm_rag/infrastructure/api/app.py` (mount `/widget` static dir)

### Step 3.1: Create the directory

```bash
mkdir -p /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/widget
```

### Step 3.2: Write the widget JS

Create `widget/widget.js`:

```javascript
/**
 * TFM RAG Chatbot Widget — vanilla JS, Shadow DOM, ~400 LOC.
 *
 * Embed:
 *   <script
 *     src="https://your-host/widget/widget.js"
 *     data-public-key="wgt_xxxxx"
 *     data-api-base="https://your-host"
 *     async
 *   ></script>
 *
 * The widget reads its own script tag for config, fetches the chatbot's
 * widget_config from /api/public/chatbots/{public_key}/config, then renders
 * a chat bubble in the page corner. Click → expand → chat.
 *
 * Session continuity: the widget generates a random `public_session_cookie`
 * on first load and persists it (plus the resulting session_id) in
 * localStorage under a per-public-key key. Reload → resume the same chat.
 */
(function () {
  "use strict";

  const SCRIPT_EL = document.currentScript;
  if (!SCRIPT_EL) {
    console.error("[tfm-widget] could not find currentScript; aborting");
    return;
  }

  const PUBLIC_KEY = SCRIPT_EL.getAttribute("data-public-key");
  if (!PUBLIC_KEY) {
    console.error("[tfm-widget] missing data-public-key on <script>");
    return;
  }
  const API_BASE = (
    SCRIPT_EL.getAttribute("data-api-base") || new URL(SCRIPT_EL.src).origin
  ).replace(/\/$/, "");

  const STORAGE_KEY = `tfm-widget:${PUBLIC_KEY}`;

  // ---- state persistence ---------------------------------------------------

  function loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return { cookie: null, session_id: null, messages: [] };
      const parsed = JSON.parse(raw);
      return {
        cookie: parsed.cookie || null,
        session_id: parsed.session_id || null,
        messages: Array.isArray(parsed.messages) ? parsed.messages : [],
      };
    } catch (e) {
      return { cookie: null, session_id: null, messages: [] };
    }
  }

  function saveState(state) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (e) {
      /* quota / private mode — ignore */
    }
  }

  function generateCookie() {
    // Crypto-strength random; falls back to Math.random in ancient browsers.
    if (window.crypto && window.crypto.getRandomValues) {
      const buf = new Uint8Array(24);
      window.crypto.getRandomValues(buf);
      return Array.from(buf)
        .map((b) => b.toString(16).padStart(2, "0"))
        .join("");
    }
    return (
      Math.random().toString(36).slice(2) +
      Math.random().toString(36).slice(2)
    );
  }

  const state = loadState();
  if (!state.cookie) {
    state.cookie = generateCookie();
    saveState(state);
  }

  // ---- root container in Shadow DOM ----------------------------------------

  const host = document.createElement("div");
  host.id = "tfm-widget-host";
  host.style.cssText = "position:fixed;z-index:2147483647;";
  document.body.appendChild(host);
  const root = host.attachShadow({ mode: "open" });

  // ---- styles + markup -----------------------------------------------------

  const style = document.createElement("style");
  style.textContent = `
    :host, *, *::before, *::after { box-sizing: border-box; }
    .bubble {
      position: fixed; bottom: 20px; width: 56px; height: 56px;
      border-radius: 28px; border: none; cursor: pointer;
      box-shadow: 0 4px 12px rgba(0,0,0,0.15);
      color: #fff; font-size: 28px; line-height: 56px;
      transition: transform .15s ease;
    }
    .bubble:hover { transform: scale(1.05); }
    .panel {
      position: fixed; bottom: 88px; width: 360px; max-width: 92vw;
      height: 520px; max-height: 80vh; border-radius: 12px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.2);
      display: none; flex-direction: column; overflow: hidden;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                   Helvetica, Arial, sans-serif;
    }
    .panel.open { display: flex; }
    .panel.theme-light { background: #fff; color: #111; }
    .panel.theme-dark { background: #1f2937; color: #f9fafb; }
    .header {
      padding: 12px 16px; color: #fff;
      display: flex; align-items: center; justify-content: space-between;
    }
    .header-title { font-weight: 600; font-size: 15px; }
    .header-close {
      background: none; border: none; color: inherit; cursor: pointer;
      font-size: 20px; line-height: 1; padding: 0 4px;
    }
    .messages {
      flex: 1; padding: 12px 14px; overflow-y: auto;
      display: flex; flex-direction: column; gap: 8px;
    }
    .msg {
      max-width: 85%; padding: 8px 12px; border-radius: 12px;
      font-size: 14px; line-height: 1.4; white-space: pre-wrap;
      word-wrap: break-word;
    }
    .msg.user { align-self: flex-end; color: #fff; }
    .panel.theme-light .msg.assistant { background: #f3f4f6; color: #111; }
    .panel.theme-dark .msg.assistant { background: #374151; color: #f9fafb; }
    .typing {
      padding: 8px 12px; opacity: 0.7; font-size: 14px;
      align-self: flex-start;
    }
    .input-row {
      display: flex; gap: 8px; padding: 10px 12px;
      border-top: 1px solid rgba(0,0,0,0.08);
    }
    .panel.theme-dark .input-row {
      border-top: 1px solid rgba(255,255,255,0.08);
    }
    .input {
      flex: 1; resize: none; border: 1px solid rgba(0,0,0,0.15);
      border-radius: 8px; padding: 8px 10px; font: inherit;
      background: inherit; color: inherit;
    }
    .panel.theme-dark .input { border-color: rgba(255,255,255,0.15); }
    .input:focus { outline: none; border-color: var(--primary, #3b82f6); }
    .send {
      border: none; border-radius: 8px; padding: 0 14px; color: #fff;
      font-weight: 600; cursor: pointer;
    }
    .send:disabled { opacity: 0.5; cursor: default; }
  `;
  root.appendChild(style);

  const panel = document.createElement("div");
  panel.className = "panel theme-light";
  root.appendChild(panel);

  const bubble = document.createElement("button");
  bubble.className = "bubble";
  bubble.textContent = "💬";
  bubble.setAttribute("aria-label", "Open chat");
  root.appendChild(bubble);

  // Slots we'll fill once config arrives:
  let messagesEl = null;
  let inputEl = null;
  let sendEl = null;

  // ---- API client ----------------------------------------------------------

  async function fetchConfig() {
    const r = await fetch(
      `${API_BASE}/api/public/chatbots/${encodeURIComponent(PUBLIC_KEY)}/config`,
      { mode: "cors" }
    );
    if (!r.ok) throw new Error(`config fetch ${r.status}`);
    return r.json();
  }

  async function postChat(messageText) {
    const r = await fetch(
      `${API_BASE}/api/public/chatbots/${encodeURIComponent(PUBLIC_KEY)}/chat`,
      {
        method: "POST",
        mode: "cors",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          session_id: state.session_id,
          public_session_cookie: state.cookie,
          message: messageText,
        }),
      }
    );
    if (!r.ok) {
      const text = await r.text();
      throw new Error(`chat ${r.status}: ${text}`);
    }
    return r.json();
  }

  // ---- UI rendering --------------------------------------------------------

  function applyConfig(cfg) {
    const w = cfg.widget || {};
    const primary = w.primary_color || "#3b82f6";
    panel.style.setProperty("--primary", primary);
    panel.className = `panel theme-${w.theme === "dark" ? "dark" : "light"}`;
    bubble.style.background = primary;
    // Position (bottom-left vs bottom-right):
    const side = w.position === "bottom-left" ? "left" : "right";
    bubble.style[side] = "20px";
    panel.style[side] = "20px";
    bubble.style[side === "left" ? "right" : "left"] = "auto";
    panel.style[side === "left" ? "right" : "left"] = "auto";

    // Header
    const header = document.createElement("div");
    header.className = "header";
    header.style.background = primary;
    const title = document.createElement("div");
    title.className = "header-title";
    title.textContent = w.title || "Asistente";
    const closeBtn = document.createElement("button");
    closeBtn.className = "header-close";
    closeBtn.setAttribute("aria-label", "Close chat");
    closeBtn.textContent = "✕";
    closeBtn.addEventListener("click", () => panel.classList.remove("open"));
    header.appendChild(title);
    header.appendChild(closeBtn);
    panel.appendChild(header);

    // Message list
    messagesEl = document.createElement("div");
    messagesEl.className = "messages";
    panel.appendChild(messagesEl);

    // Input row
    const row = document.createElement("div");
    row.className = "input-row";
    inputEl = document.createElement("textarea");
    inputEl.className = "input";
    inputEl.rows = 1;
    inputEl.placeholder = w.placeholder || "Escribe tu pregunta...";
    sendEl = document.createElement("button");
    sendEl.className = "send";
    sendEl.style.background = primary;
    sendEl.textContent = "Enviar";
    row.appendChild(inputEl);
    row.appendChild(sendEl);
    panel.appendChild(row);

    // Restore prior conversation
    if (state.messages.length === 0 && w.welcome_message) {
      addMessage("assistant", w.welcome_message);
    } else {
      for (const m of state.messages) addMessage(m.role, m.content);
    }

    // Wire interactions
    bubble.addEventListener("click", () => {
      panel.classList.toggle("open");
      if (panel.classList.contains("open")) {
        setTimeout(() => inputEl.focus(), 50);
      }
    });
    sendEl.addEventListener("click", onSend);
    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        onSend();
      }
    });
  }

  function addMessage(role, content) {
    const el = document.createElement("div");
    el.className = `msg ${role}`;
    if (role === "user") el.style.background = bubble.style.background;
    el.textContent = content;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  let pending = false;
  async function onSend() {
    if (pending) return;
    const text = inputEl.value.trim();
    if (!text) return;

    inputEl.value = "";
    addMessage("user", text);
    state.messages.push({ role: "user", content: text });
    saveState(state);

    const typing = document.createElement("div");
    typing.className = "typing";
    typing.textContent = "...";
    messagesEl.appendChild(typing);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    sendEl.disabled = true;
    pending = true;

    try {
      const resp = await postChat(text);
      typing.remove();
      addMessage("assistant", resp.content);
      state.messages.push({ role: "assistant", content: resp.content });
      state.session_id = resp.session_id;
      saveState(state);
    } catch (e) {
      typing.remove();
      addMessage(
        "assistant",
        "Lo siento, no he podido responder ahora. Inténtalo de nuevo en un momento."
      );
      console.error("[tfm-widget] chat error", e);
    } finally {
      sendEl.disabled = false;
      pending = false;
      inputEl.focus();
    }
  }

  // ---- bootstrap -----------------------------------------------------------

  fetchConfig()
    .then(applyConfig)
    .catch((e) => {
      console.error("[tfm-widget] config fetch failed", e);
      // Render a minimal fallback so at least the bubble shows up
      applyConfig({
        widget: {
          theme: "light",
          primary_color: "#3b82f6",
          position: "bottom-right",
          title: "Asistente",
          welcome_message: "",
          placeholder: "Escribe tu pregunta...",
        },
      });
    });
})();
```

### Step 3.3: Write a tiny demo HTML

Create `widget/index.html`:

```html
<!DOCTYPE html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <title>TFM RAG Widget — demo</title>
    <style>
      body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
          Helvetica, Arial, sans-serif;
        max-width: 720px;
        margin: 64px auto;
        padding: 0 24px;
        line-height: 1.55;
        color: #111;
      }
      .frame {
        background: #f5f5f5;
        padding: 12px 16px;
        border-radius: 8px;
        font-family: ui-monospace, SFMono-Regular, monospace;
        font-size: 13px;
        white-space: pre-wrap;
        word-break: break-all;
      }
    </style>
  </head>
  <body>
    <h1>TFM RAG Chatbot — Widget demo</h1>
    <p>
      This page is a local manual-test harness for
      <code>widget.js</code>. The widget is loaded with a placeholder
      public_key. To test against a real chatbot, edit the
      <code>data-public-key</code> attribute below to point at one of
      <em>your</em> chatbots and reload.
    </p>
    <p>Embed snippet for production:</p>
    <pre class="frame">&lt;script
  src="https://your-host/widget/widget.js"
  data-public-key="wgt_..."
  data-api-base="https://your-host"
  async
&gt;&lt;/script&gt;</pre>
    <p>
      Open the browser dev console: any failures (bad public_key, CORS
      mismatch) are logged there.
    </p>

    <!-- Edit data-public-key + data-api-base before testing. -->
    <script
      src="./widget.js"
      data-public-key="wgt_REPLACE_ME"
      data-api-base="http://localhost:8000"
      async
    ></script>
  </body>
</html>
```

### Step 3.4: Mount static files in FastAPI

Open `backend/src/tfm_rag/infrastructure/api/app.py`. Add at the top:

```python
from pathlib import Path

from fastapi.staticfiles import StaticFiles
```

In `create_app()`, AFTER all `app.include_router(...)` calls:

```python
    # Serve the embeddable widget JS + demo HTML from the `widget/` directory
    # at the repo root. The path is resolved relative to this file so it
    # works regardless of cwd.
    widget_dir = Path(__file__).resolve().parents[5] / "widget"
    if widget_dir.is_dir():
        app.mount(
            "/widget",
            StaticFiles(directory=str(widget_dir), html=True),
            name="widget",
        )
```

`Path(__file__).resolve().parents[5]` walks from `backend/src/tfm_rag/infrastructure/api/app.py` up to the repo root (parents[0]=api, [1]=infrastructure, [2]=tfm_rag, [3]=src, [4]=backend, [5]=repo). Confirm with:

```bash
python -c "
from pathlib import Path
p = Path('backend/src/tfm_rag/infrastructure/api/app.py').resolve()
for i, parent in enumerate(p.parents):
    print(i, parent)
" | head -8
```

Adjust the `parents[N]` index if needed.

The `html=True` flag makes `GET /widget/` serve `index.html` automatically.

### Step 3.5: Smoke-test the widget mount

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
python -c "
from tfm_rag.infrastructure.api.app import app
for route in app.routes:
    if hasattr(route, 'path') and 'widget' in route.path:
        print(route.path)
"
```

Expected: prints `/widget`.

If you can run the server:

```bash
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
uvicorn tfm_rag.infrastructure.api.app:app --port 8000 &
sleep 2
curl -sI http://localhost:8000/widget/widget.js | head -5
kill %1
```

Expected: 200 OK and `content-type: text/javascript` (or `application/javascript`).

### Step 3.6: Commit

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add widget/widget.js widget/index.html \
        backend/src/tfm_rag/infrastructure/api/app.py
git commit -m "feat(widget): vanilla-JS embeddable widget + StaticFiles mount at /widget (plan #16 Task 3)"
```

---

## Task 4 — E2E integration test

**Files:**
- Create: `backend/tests/integration/test_public_widget_endpoints.py`

The test:
1. Registers a tenant + KB + chatbot via the authenticated endpoints (this gives us a real `public_key`).
2. Calls `GET /api/public/chatbots/{public_key}/config` — asserts the widget config round-trips.
3. Calls `POST /api/public/chatbots/{public_key}/chat` with a cookie + no session_id — asserts answer + session_id back.
4. Calls again with the same cookie + the returned session_id — asserts no 403.
5. Calls with a wrong cookie + the same session_id — asserts 403.
6. Asserts the chat_session row has `origin="widget"`.
7. Asserts `GET /widget/widget.js` serves the file content (200, with `"data-public-key"` substring in the body).

### Step 4.1: Create the test

Create `backend/tests/integration/test_public_widget_endpoints.py`:

```python
"""E2E for CAP-WIDGET-RUNTIME — public widget endpoints + static serving."""
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

import tfm_rag.infrastructure.api.dependencies as _deps
from tfm_rag.infrastructure.api.app import app
from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.persistence.models.chat_sessions import (
    ChatSessionRow,
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
            "chatbot_knowledge_base, chatbots, ingestion_jobs, "
            "sources, knowledge_bases, provider_credentials, "
            "users, tenants RESTART IDENTITY CASCADE"
        ))
        await s.commit()
    await engine.dispose()
    _deps._session_factory = None


async def _bootstrap_chatbot(c: AsyncClient) -> dict[str, Any]:
    r = await c.post(
        "/api/auth/register",
        json={"email": "widget-e2e@example.com", "password": "correctpassword"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    h = {"Authorization": f"Bearer {token}"}

    creds = (await c.get("/api/credentials", headers=h)).json()
    cred_id = next(x for x in creds if x["provider_id"] == "ollama")["id"]

    r = await c.post(
        "/api/knowledge-bases", headers=h,
        json={
            "name": "WidgetKB",
            "embedding_selection": {
                "provider_id": "ollama", "credential_id": cred_id,
                "model_id": "bge-m3", "dim": 1024,
            },
            "chunking_config": {
                "strategy": "fixed", "chunk_size": 300, "chunk_overlap": 50,
            },
        },
    )
    kb_id = r.json()["id"]

    r = await c.post(
        "/api/chatbots", headers=h,
        json={
            "name": "WidgetBot",
            "system_prompt": "Sé conciso.",
            "llm_selection": {
                "provider_id": "ollama", "credential_id": cred_id,
                "model_id": "llama3.1",
            },
            "kb_ids": [kb_id],
            "pipeline_config": {"top_k": 3, "max_retrieval_iterations": 2},
            "widget_config": {
                "theme": "dark",
                "primary_color": "#10b981",
                "title": "TestBot",
                "welcome_message": "¡Hola!",
                "placeholder": "Pregunta...",
                "allowed_origins": ["https://acme.example.com"],
            },
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return {
        "chatbot_id": body["id"],
        "public_key": body["public_key"],
    }


async def test_widget_config_endpoint_returns_safe_subset(
    _clean_state: None,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        info = await _bootstrap_chatbot(c)
        r = await c.get(
            f"/api/public/chatbots/{info['public_key']}/config",
            headers={"Origin": "https://acme.example.com"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chatbot_id"] == info["chatbot_id"]
    assert body["name"] == "WidgetBot"
    w = body["widget"]
    assert w["theme"] == "dark"
    assert w["primary_color"] == "#10b981"
    assert w["title"] == "TestBot"
    assert w["welcome_message"] == "¡Hola!"
    assert "system_prompt" not in body  # MUST NOT leak

    # CORS allowed because Origin matches widget_config.allowed_origins
    assert r.headers.get("access-control-allow-origin") == (
        "https://acme.example.com"
    )


async def test_widget_config_returns_404_for_unknown_public_key(
    _clean_state: None,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/public/chatbots/wgt_bogus/config")
    assert r.status_code == 404


async def test_widget_cors_does_not_echo_unknown_origin(
    _clean_state: None,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        info = await _bootstrap_chatbot(c)
        r = await c.get(
            f"/api/public/chatbots/{info['public_key']}/config",
            headers={"Origin": "https://attacker.example.com"},
        )
    # The endpoint still returns 200 — CORS narrowing is enforced by the
    # BROWSER reading the Access-Control-Allow-Origin header. We assert
    # the header is absent or doesn't match the attacker.
    allowed = r.headers.get("access-control-allow-origin")
    assert allowed != "https://attacker.example.com"


async def test_widget_chat_creates_widget_session_and_round_trip(
    _clean_state: None, settings: Settings,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=120.0,
    ) as c:
        info = await _bootstrap_chatbot(c)
        cookie = "test-cookie-" + "abcd" * 6
        r = await c.post(
            f"/api/public/chatbots/{info['public_key']}/chat",
            json={
                "session_id": None,
                "public_session_cookie": cookie,
                "message": "Hola, ¿qué puedes hacer?",
            },
            headers={"Origin": "https://acme.example.com"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["content"], "non-empty answer"
    session_id_str = body["session_id"]

    # Verify the chat_session row has origin="widget" + cookie.
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    async with factory() as s:
        row = (
            await s.execute(
                select(ChatSessionRow).where(
                    ChatSessionRow.id == UUID(session_id_str)
                )
            )
        ).scalar_one()
        assert row.origin == "widget"
        assert row.public_session_cookie == cookie
    await engine.dispose()


async def test_widget_chat_rejects_wrong_cookie_on_session_reuse(
    _clean_state: None,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=120.0,
    ) as c:
        info = await _bootstrap_chatbot(c)
        cookie = "good-cookie-" + "x" * 32
        r1 = await c.post(
            f"/api/public/chatbots/{info['public_key']}/chat",
            json={
                "session_id": None,
                "public_session_cookie": cookie,
                "message": "Primera",
            },
        )
        assert r1.status_code == 200, r1.text
        session_id = r1.json()["session_id"]

        # Replay with the WRONG cookie — must 403.
        r2 = await c.post(
            f"/api/public/chatbots/{info['public_key']}/chat",
            json={
                "session_id": session_id,
                "public_session_cookie": "wrong-cookie",
                "message": "Segunda",
            },
        )
    assert r2.status_code == 403
    assert "cookie" in r2.json()["detail"].lower()


async def test_widget_js_is_served_as_static_file(_clean_state: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/widget/widget.js")
    assert r.status_code == 200, r.text
    # Verify it actually looks like our widget.
    body_text = r.text
    assert "TFM RAG Chatbot Widget" in body_text
    assert "data-public-key" in body_text
    assert "shadowRoot" in body_text or "attachShadow" in body_text
```

### Step 4.2: Run the test

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
pytest tests/integration/test_public_widget_endpoints.py -m integration -v --timeout=300 2>&1 | tail -30
```

Expected: **6 passed** (the chat round-trip + the static file serving).

**If `test_widget_js_is_served_as_static_file` fails with 404**: the `Path(__file__).parents[N]` index is wrong. Fix Task 3.4's mount path. Print `widget_dir` in a temp print to confirm it resolves to the repo's `widget/` folder.

**If `test_widget_chat_creates_widget_session_and_round_trip` times out**: Ollama may have cold-started. Re-run once. If persistent, raise the timeout to 240s.

### Step 4.3: Run the full integration suite

```bash
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
pytest tests/integration -m integration --timeout=900 2>&1 | tail -10
```

Expected: previous (41 passed + 1 flake) + 6 new = **47 PASSED / 48 total**.

### Step 4.4: Commit + tag

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/tests/integration/test_public_widget_endpoints.py
git commit -m "test(widget): e2e public endpoints + cookie verification + static file serving (plan #16 Task 4)"
git tag cap-16-widget-runtime
```

---

## Controller cleanup (post-subagent — NOT a task)

After all 4 tasks land:

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
ruff check . --fix
mypy src/
pytest tests/ -m "not integration"
```

If autofixes apply:

```bash
git add <files>
git commit -m "chore(plan-16): ruff autofix + mypy fix"
git tag -f cap-16-widget-runtime <cleanup-commit-sha>
```

---

## What's next after plan #16

**All 17 plans landed.** The MVP is complete: M1 → M5 + M6 demoable end-to-end.

Follow-ups worth considering (out of scope of plan #16 but small):

- **Snippet copy + live preview in admin panel** — a frontend page that shows the `<script>` snippet (with the right `data-public-key`) and renders the widget inline for design tweaking.
- **Rate limiting on public endpoints** — `slowapi` or similar; per-IP + per-public_key.
- **WebSocket streaming** — replace the `POST /chat` with a WS so tokens stream as the LLM generates them. Big UX win; needs `answer_query` to expose a generator.
- **Custom domain support** — let tenants point `chat.theirdomain.com` to the widget URL via a CNAME and a small bit of routing.
- **i18n** — the widget UI strings are Spanish; allow `widget_config.locale` + serve translated strings from the config endpoint.
- **Markdown rendering** — render assistant bubbles as markdown (currently `textContent`).
