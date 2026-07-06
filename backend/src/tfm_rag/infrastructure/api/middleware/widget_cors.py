"""CORS middleware for the app: restrictive by default, permissive for the
public widget surface.

The global ``CORSMiddleware`` calls ``headers.update(simple_headers)`` for
every response that carries an ``Origin`` request header. When
``allow_origins=["*"]`` this unconditionally sets
``Access-Control-Allow-Origin: *``, overwriting the per-chatbot value that
the route handler already placed there.

This module provides two classes:
  * ``NonOverwritingCORSMiddleware`` — a thin subclass of ``CORSMiddleware``
    that skips the wildcard injection when the response already carries an
    explicit ``Access-Control-Allow-Origin`` header set by the route.
  * ``PathScopedCORSMiddleware`` — the one actually mounted on the app
    (see ``infrastructure.api.app``). It dispatches between a restrictive
    ``NonOverwritingCORSMiddleware`` (settings-derived allow-list, for the
    authenticated API) and a permissive one (for ``/api/public/*``, the
    embeddable widget surface) based on the request path. See its own
    docstring for why a single instance can't do both.
"""

import functools
from collections.abc import Sequence
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class NonOverwritingCORSMiddleware(CORSMiddleware):
    """Subclass of ``CORSMiddleware`` that preserves a per-route
    ``Access-Control-Allow-Origin`` header when one is already present.

    All other behaviour (OPTIONS preflight handling, method/header allow-lists,
    ``Vary`` injection) is inherited unchanged from the parent class.
    """

    def __init__(self, app: ASGIApp, **kwargs: Any) -> None:
        super().__init__(app, **kwargs)

    async def send(
        self,
        message: Message,
        send: Send,
        request_headers: Any,
    ) -> None:
        if message["type"] != "http.response.start":
            await send(message)
            return

        # Check if the route already set an explicit ACAO header.
        headers = MutableHeaders(scope=message)
        if "access-control-allow-origin" in headers:
            # Route already decided; do NOT overwrite with the wildcard.
            # But we still need to ensure the other CORS headers are present
            # so preflight responses work correctly in browsers.
            if "access-control-allow-methods" not in headers:
                headers.append(
                    "access-control-allow-methods",
                    ", ".join(self.allow_methods),
                )
            if "access-control-allow-headers" not in headers:
                headers.append(
                    "access-control-allow-headers",
                    ", ".join(self.allow_headers),
                )
            if "vary" not in headers:
                headers.append("vary", "Origin")
            await send(message)
            return

        # No explicit header set — delegate to the parent logic which will
        # inject `*` (or the echoed origin, if credentials are allowed).
        await super().send(message, send=send, request_headers=request_headers)

    async def simple_response(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        request_headers: Any,
    ) -> None:
        send = functools.partial(self.send, send=send, request_headers=request_headers)
        await self.app(scope, receive, send)


class PathScopedCORSMiddleware:
    """Applies a permissive CORS policy to the public widget surface and a
    restrictive one (`settings.frontend_origin`) to everything else.

    Starlette's `CORSMiddleware` handles an OPTIONS preflight entirely by
    itself — for a disallowed origin it returns 400 *without ever calling
    the downstream app*. That means a single, restrictive `allow_origins`
    list would reject the embeddable widget's cross-origin preflight (any
    JSON POST triggers one) to `/api/public/*` before the per-chatbot
    `application.chat.widget_cors.resolve_allowed_origin` decision — applied
    inside the route handler — ever got a chance to run.

    So this dispatches each request to one of two fully independent
    `NonOverwritingCORSMiddleware` instances based on path prefix:
      * `/api/public/*` → permissive (`allow_origins=["*"]`). The actual
        `Access-Control-Allow-Origin` value is still narrowed per-chatbot by
        the route handler; `NonOverwritingCORSMiddleware` just avoids
        clobbering that with the wildcard.
      * everything else → restricted to `restricted_origins` (normally
        `settings.frontend_origin`, comma-split).

    No shared mutable state between the two instances (each wraps the same
    downstream `app` independently), so this is safe under concurrent
    requests.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        restricted_origins: Sequence[str],
        public_path_prefixes: Sequence[str] = ("/api/public/",),
    ) -> None:
        self._public_prefixes = tuple(public_path_prefixes)
        common_kwargs: dict[str, Any] = {
            "allow_credentials": False,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }
        self._public = NonOverwritingCORSMiddleware(
            app, allow_origins=["*"], **common_kwargs,
        )
        self._restricted = NonOverwritingCORSMiddleware(
            app, allow_origins=list(restricted_origins), **common_kwargs,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and any(
            scope["path"].startswith(p) for p in self._public_prefixes
        ):
            await self._public(scope, receive, send)
            return
        await self._restricted(scope, receive, send)

