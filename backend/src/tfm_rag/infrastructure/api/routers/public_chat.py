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


# --- POST /chat ---------------------------------------------------------------

from uuid import UUID  # noqa: E402

from tfm_rag.application.chat.answer_query import answer_query  # noqa: E402
from tfm_rag.infrastructure.embedders.dispatcher import EmbedderDispatcher  # noqa: E402
from tfm_rag.infrastructure.llm_providers.dispatcher import LLMDispatcher  # noqa: E402
from tfm_rag.infrastructure.persistence.models.chat_sessions import (  # noqa: E402
    ChatSessionRow,
)
from tfm_rag.infrastructure.settings import Settings, get_settings  # noqa: E402
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore  # noqa: E402
from tfm_rag.infrastructure.api.routers.chatbots import ChatOut  # noqa: E402


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
        from sqlalchemy import select  # noqa: PLC0415

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
