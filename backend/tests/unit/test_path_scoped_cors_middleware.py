"""Task 4 (T12): app-level CORS must stop being `allow_origins=["*"]` and
instead derive its allow-list from `settings.frontend_origin` — EXCEPT for
the public widget surface (`/api/public/*`), which must remain reachable
cross-origin from arbitrary third-party sites embedding the widget.

Why the split matters: a browser preflights any JSON POST (the widget's
chat/config calls carry a JSON body). Starlette's `CORSMiddleware` rejects
that preflight outright (400) for any `Origin` not in its configured
`allow_origins` — it never reaches the route. So if a single, restrictive
CORSMiddleware were applied globally, the widget's cross-origin preflight
to `/api/public/*` would fail before the per-chatbot
`resolve_allowed_origin` logic (applied inside the route handler) ever got
a chance to run. `PathScopedCORSMiddleware` keeps the public surface's
preflight permissive while restricting everything else.
"""
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from tfm_rag.infrastructure.api.middleware.widget_cors import (
    PathScopedCORSMiddleware,
)

RESTRICTED_ORIGINS = ["https://app.example.com"]


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        PathScopedCORSMiddleware,
        restricted_origins=RESTRICTED_ORIGINS,
    )

    @app.get("/api/private/ping")
    async def ping() -> dict:
        return {"ok": True}

    @app.post("/api/private/ping")
    async def ping_post() -> dict:
        return {"ok": True}

    @app.get("/api/public/chatbots/x/config")
    async def public_config_no_explicit_header() -> dict:
        # Simulates a public route that found no matching per-chatbot
        # origin (e.g. chatbot has no allowed_origins configured) and so
        # sets no explicit ACAO header itself.
        return {"ok": True}

    @app.post("/api/public/chatbots/x/chat")
    async def public_chat_with_explicit_header(request: Request, response: Response) -> dict:
        # Simulates the real route: it already narrowed the CORS decision
        # per-chatbot (via application.chat.widget_cors.resolve_allowed_origin,
        # covered by its own unit tests) and set the header itself.
        origin = request.headers.get("origin")
        if origin is not None:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        return {"ok": True}

    return app


# --- restricted (non-public) surface ----------------------------------------


def test_private_route_preflight_from_allowed_origin_succeeds() -> None:
    client = TestClient(_build_app())
    resp = client.options(
        "/api/private/ping",
        headers={
            "Origin": "https://app.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "https://app.example.com"


def test_private_route_preflight_from_disallowed_origin_is_rejected() -> None:
    client = TestClient(_build_app())
    resp = client.options(
        "/api/private/ping",
        headers={
            "Origin": "https://attacker.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 400


def test_private_route_actual_response_from_disallowed_origin_has_no_acao() -> None:
    client = TestClient(_build_app())
    resp = client.get(
        "/api/private/ping", headers={"Origin": "https://attacker.example.com"}
    )
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


def test_private_route_actual_response_from_allowed_origin_echoes_it() -> None:
    client = TestClient(_build_app())
    resp = client.get(
        "/api/private/ping", headers={"Origin": "https://app.example.com"}
    )
    assert resp.headers["access-control-allow-origin"] == "https://app.example.com"


# --- public widget surface ---------------------------------------------------


def test_public_route_preflight_from_arbitrary_third_party_origin_succeeds() -> None:
    """The crux of T12: an origin NOT in the restricted allow-list must
    still pass CORS preflight for the public widget surface."""
    client = TestClient(_build_app())
    resp = client.options(
        "/api/public/chatbots/x/chat",
        headers={
            "Origin": "https://third-party-widget-host.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resp.status_code == 200


def test_public_route_explicit_per_chatbot_header_is_not_overwritten() -> None:
    """Coexistence test: the route's own (per-chatbot-narrowed) ACAO header
    for an arbitrary third-party origin must survive the app-level
    middleware unmodified — not overwritten to `*` nor stripped."""
    client = TestClient(_build_app())
    origin = "https://third-party-widget-host.example"
    resp = client.post(
        "/api/public/chatbots/x/chat",
        headers={"Origin": origin},
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == origin


def test_public_route_without_explicit_header_falls_back_to_permissive() -> None:
    """When the route itself sets no ACAO (e.g. chatbot has no
    allowed_origins), the public-surface middleware still responds
    permissively (parity with the previous global `*` behaviour) rather
    than silently applying the restrictive allow-list.
    """
    client = TestClient(_build_app())
    resp = client.get(
        "/api/public/chatbots/x/config",
        headers={"Origin": "https://third-party-widget-host.example"},
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "*"
