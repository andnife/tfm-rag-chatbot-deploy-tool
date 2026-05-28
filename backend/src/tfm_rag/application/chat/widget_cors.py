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
      * `allowed_origins` is empty (owner didn't restrict) → return None
        (deny by default to prevent cross-origin abuse).
      * `*` is in the list → echo request_origin.
      * request_origin matches an entry exactly (case-sensitive, port/scheme
        included) → echo request_origin.
      * Otherwise → None.
    """
    if request_origin is None:
        return None
    allowed_tuple = tuple(allowed_origins)
    if not allowed_tuple:
        return None
    if "*" in allowed_tuple:
        return request_origin
    if request_origin in allowed_tuple:
        return request_origin
    return None
