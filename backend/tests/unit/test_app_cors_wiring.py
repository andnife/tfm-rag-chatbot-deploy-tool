"""Task 4 (T12): end-to-end proof that `create_app()` wires the restrictive
(`settings.frontend_origin`) and permissive (public widget) CORS policies
together correctly — coexistence of both policies on the real app, not just
on a synthetic test app (see `test_path_scoped_cors_middleware.py` for the
unit-level behaviour of `PathScopedCORSMiddleware` itself).

Only exercises CORS preflight (OPTIONS), which `CORSMiddleware` answers
without ever calling the downstream app/route — so no DB/Qdrant/Ollama
connectivity is needed.
"""
from fastapi.testclient import TestClient

from tfm_rag.infrastructure.api.app import create_app

THIRD_PARTY_ORIGIN = "https://third-party-widget-host.example"


def test_public_widget_preflight_succeeds_from_third_party_origin() -> None:
    """The default `frontend_origin` is `http://localhost:3000` — this
    third-party origin is NOT in that list, yet the widget's public chat
    endpoint must still pass CORS preflight (its actual response is
    narrowed per-chatbot inside the route, not by the app-level policy).
    """
    client = TestClient(create_app())

    resp = client.options(
        "/api/public/chatbots/some-public-key/chat",
        headers={
            "Origin": THIRD_PARTY_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert resp.status_code == 200, resp.text


def test_authenticated_surface_preflight_rejects_the_same_third_party_origin() -> None:
    """The very same origin must be rejected for a non-public, authenticated
    route (here `/api/incidents`, mounted by this task) — proving the
    restrictive policy actually applies outside `/api/public/*`.
    """
    client = TestClient(create_app())

    resp = client.options(
        "/api/incidents",
        headers={
            "Origin": THIRD_PARTY_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert resp.status_code == 400
