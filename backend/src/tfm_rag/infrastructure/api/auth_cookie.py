"""Single source of truth for the auth cookie used by the Next.js frontend.

The JWT (24h by default, `settings.jwt_expires_hours`; no DB revocation) is
delivered as an httpOnly cookie so the Next middleware can gate routes and
the browser never exposes the token to JS. The backend reads the token from
the cookie OR the `Authorization: Bearer` header (header kept for pytest,
integration, widget).
"""
from typing import Any

from fastapi import Response

COOKIE_NAME = "tfm_rag_token"


def set_auth_cookie(response: Response, token: str, *, secure: bool, max_age: int) -> None:
    # "Lax" (not lowercase "lax") is the wire value pinned by test_auth_cookie.py;
    # SameSite is case-insensitive per RFC 6265bis, but Starlette's stub is
    # narrower than the spec, hence the ignore.
    response.set_cookie(
        key=COOKIE_NAME, value=token, max_age=max_age,
        httponly=True, samesite="Lax",  # type: ignore[arg-type]
        secure=secure, path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.set_cookie(
        key=COOKIE_NAME, value="", max_age=0,
        httponly=True, samesite="Lax", path="/",  # type: ignore[arg-type]
    )


def extract_token(request: Any) -> str | None:
    """Return the JWT from the cookie (preferred) or the Bearer header."""
    cookie_val: str | None = getattr(request, "cookies", {}).get(COOKIE_NAME)
    if cookie_val:
        return cookie_val
    auth = getattr(request, "headers", {}).get("authorization", "")
    if auth.lower().startswith("bearer "):
        stripped = auth.split(" ", 1)[1].strip()
        return stripped if stripped else None
    return None
