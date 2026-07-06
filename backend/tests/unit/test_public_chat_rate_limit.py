"""Task 4 (T2): rate limiting wired onto the public widget endpoints.

Two layers are tested:
  1. The FastAPI dependency functions directly (fast, no DB/app needed) —
     verifies key composition (per public_key + client IP) and the 429 +
     Retry-After shape.
  2. An end-to-end TestClient hit against the real router (DB session and
     the chatbot lookup mocked out) — verifies the dependency is actually
     wired onto the routes.
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from tfm_rag.application.chatbot_config.get_chatbot_by_public_key import (
    PublicKeyNotFoundError,
)
from tfm_rag.infrastructure.api.app import create_app
from tfm_rag.infrastructure.api.dependencies import get_session
from tfm_rag.infrastructure.api.rate_limiting import TokenBucketRateLimiter
from tfm_rag.infrastructure.api.routers import public_chat
from tfm_rag.infrastructure.settings import Settings, get_settings


class _FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def _make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = dict(
        postgres_url="postgresql+asyncpg://u:p@h:5432/d",
        qdrant_url="http://qdrant:6333",
        ollama_base_url="http://ollama:11434",
        jwt_secret="x" * 32,
        fernet_key="qjd374RRcCpzdVhmmLHCnjxvBfrFwbwErhxIj4nq_XM=",
        public_chat_rate_per_minute=60,
        public_chat_burst=2,
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _fake_request(ip: str = "1.2.3.4") -> Request:
    scope = {
        "type": "http",
        "client": (ip, 12345),
        "headers": [],
        "path_params": {},
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _reset_rate_limiter_singleton() -> None:
    public_chat._rate_limiter = None
    yield
    public_chat._rate_limiter = None


# --- dependency-level ---------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_chat_allows_up_to_burst_then_429_with_retry_after() -> None:
    settings = _make_settings(public_chat_burst=2, public_chat_rate_per_minute=60)
    public_chat._rate_limiter = TokenBucketRateLimiter(
        rate_per_minute=settings.public_chat_rate_per_minute,
        burst=settings.public_chat_burst,
        clock=_FakeClock(),
    )
    request = _fake_request()

    await public_chat.rate_limit_chat(request=request, public_key="abc", settings=settings)
    await public_chat.rate_limit_chat(request=request, public_key="abc", settings=settings)

    with pytest.raises(HTTPException) as exc_info:
        await public_chat.rate_limit_chat(request=request, public_key="abc", settings=settings)

    assert exc_info.value.status_code == 429
    retry_after = int(exc_info.value.headers["Retry-After"])
    assert retry_after >= 1


@pytest.mark.asyncio
async def test_rate_limit_chat_is_scoped_per_public_key_and_ip() -> None:
    settings = _make_settings(public_chat_burst=1, public_chat_rate_per_minute=60)
    public_chat._rate_limiter = TokenBucketRateLimiter(
        rate_per_minute=settings.public_chat_rate_per_minute,
        burst=settings.public_chat_burst,
        clock=_FakeClock(),
    )

    await public_chat.rate_limit_chat(
        request=_fake_request("1.1.1.1"), public_key="bot-a", settings=settings,
    )
    # Different chatbot, same IP -> independent bucket, still allowed.
    await public_chat.rate_limit_chat(
        request=_fake_request("1.1.1.1"), public_key="bot-b", settings=settings,
    )
    # Same chatbot, different IP -> independent bucket, still allowed.
    await public_chat.rate_limit_chat(
        request=_fake_request("2.2.2.2"), public_key="bot-a", settings=settings,
    )
    # Same chatbot + same IP as the first call -> bucket now empty.
    with pytest.raises(HTTPException) as exc_info:
        await public_chat.rate_limit_chat(
            request=_fake_request("1.1.1.1"), public_key="bot-a", settings=settings,
        )
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_chat_and_config_have_independent_budgets() -> None:
    settings = _make_settings(public_chat_burst=1, public_chat_rate_per_minute=60)
    public_chat._rate_limiter = TokenBucketRateLimiter(
        rate_per_minute=settings.public_chat_rate_per_minute,
        burst=settings.public_chat_burst,
        clock=_FakeClock(),
    )
    request = _fake_request()

    await public_chat.rate_limit_chat(request=request, public_key="abc", settings=settings)
    # config has its own budget even though chat's is now exhausted.
    await public_chat.rate_limit_config(request=request, public_key="abc", settings=settings)


# --- end-to-end via the real router -------------------------------------------


def _client_with_mocked_deps(settings: Settings) -> TestClient:
    app = create_app()

    async def _fake_session():
        yield object()

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app, raise_server_exceptions=True)


def test_post_chat_returns_429_with_retry_after_once_burst_is_exhausted() -> None:
    settings = _make_settings(public_chat_burst=2, public_chat_rate_per_minute=60)
    client = _client_with_mocked_deps(settings)

    with patch(
        "tfm_rag.infrastructure.api.routers.public_chat.get_chatbot_by_public_key",
        new=AsyncMock(side_effect=PublicKeyNotFoundError("chatbot not found")),
    ):
        responses = [
            client.post(
                "/api/public/chatbots/some-key/chat",
                json={"public_session_cookie": "c", "message": "hi"},
            )
            for _ in range(3)
        ]

    # First `burst` requests reach the route (and 404 — no real chatbot);
    # the one beyond the burst is rejected by the rate limiter first.
    assert [r.status_code for r in responses[:2]] == [404, 404]
    assert responses[2].status_code == 429
    assert "Retry-After" in responses[2].headers


def test_get_config_is_also_rate_limited() -> None:
    settings = _make_settings(public_chat_burst=1, public_chat_rate_per_minute=60)
    client = _client_with_mocked_deps(settings)

    with patch(
        "tfm_rag.infrastructure.api.routers.public_chat.get_chatbot_by_public_key",
        new=AsyncMock(side_effect=PublicKeyNotFoundError("chatbot not found")),
    ):
        first = client.get("/api/public/chatbots/some-key/config")
        second = client.get("/api/public/chatbots/some-key/config")

    assert first.status_code == 404
    assert second.status_code == 429
    assert "Retry-After" in second.headers
