from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from tfm_rag.infrastructure.auth.jwt import TokenInvalidError, decode_jwt
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.settings import Settings


# Paths that do NOT require an authenticated context.
UNAUTHENTICATED_PREFIXES: tuple[str, ...] = (
    "/api/auth/",
    "/api/public/",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
)


class TenantScopingMiddleware(BaseHTTPMiddleware):
    """Extracts tenant_id and user_id from the JWT and attaches them to
    `request.state.ctx`. If the path is unauthenticated, sets ctx to None.
    """

    def __init__(self, app: Callable[..., Awaitable[Response]], *, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if any(path.startswith(p) for p in UNAUTHENTICATED_PREFIXES):
            request.state.ctx = None
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return Response(
                content='{"error":{"code":"unauthenticated","message":"Missing Bearer token"}}',
                status_code=401,
                media_type="application/json",
            )
        token = auth.split(" ", 1)[1].strip()
        try:
            payload = decode_jwt(token, self._settings.jwt_secret)
        except TokenInvalidError as exc:
            return Response(
                content=f'{{"error":{{"code":"unauthenticated","message":"{exc}"}}}}',
                status_code=401,
                media_type="application/json",
            )

        request.state.ctx = RequestContext(
            tenant_id=UUID(payload["tid"]),
            user_id=UUID(payload["sub"]),
        )
        return await call_next(request)
