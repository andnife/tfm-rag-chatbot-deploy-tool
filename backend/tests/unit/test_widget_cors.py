"""Unit tests for the per-chatbot CORS resolver."""

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
