"""Shared isolation for integration tests.

The app caches a module-global async session factory (`_deps._session_factory`)
and an lru-cached `get_settings()`. Under pytest-asyncio each test can run on a
different event loop, and a factory/engine bound to a torn-down loop leaks
across tests when run together (module-ordering flakiness: registrations that
"succeed" but aren't visible, empty credential lists, etc.).

Individual test modules used to reset these globals inconsistently in their own
fixtures. This autouse fixture standardizes it: every integration test starts
(and ends) with the globals cleared, so the factory is rebuilt bound to the
current loop and settings are re-read from the current env.
"""
import pytest

import tfm_rag.infrastructure.api.dependencies as _deps
from tfm_rag.infrastructure.settings import get_settings


@pytest.fixture(autouse=True)
def _reset_app_globals() -> None:
    _deps._session_factory = None
    get_settings.cache_clear()
    yield
    _deps._session_factory = None
    get_settings.cache_clear()
