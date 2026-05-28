"""Non-overwriting CORS middleware for public widget routes.

The global ``CORSMiddleware`` (``allow_origins=["*"]``) calls
``headers.update(simple_headers)`` for every response that carries an
``Origin`` request header.  When ``allow_origins=["*"]`` this unconditionally
sets ``Access-Control-Allow-Origin: *``, overwriting the per-chatbot value
that the route handler already placed there.

This module provides ``NonOverwritingCORSMiddleware`` — a thin subclass of
``CORSMiddleware`` that skips the wildcard injection when the response already
carries an explicit ``Access-Control-Allow-Origin`` header set by the route.
"""

import functools
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

