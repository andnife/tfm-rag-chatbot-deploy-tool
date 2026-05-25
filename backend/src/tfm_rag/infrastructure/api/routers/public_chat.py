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
