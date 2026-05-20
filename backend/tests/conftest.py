import os

import pytest

from tfm_rag.infrastructure.settings import Settings


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings from the running environment (.env or docker-compose env)."""
    # Defaults for local dev if not set; integration tests expect compose up
    monkeypatch.setenv(
        "POSTGRES_URL",
        os.environ.get(
            "POSTGRES_URL",
            "postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag",
        ),
    )
    monkeypatch.setenv(
        "QDRANT_URL",
        os.environ.get("QDRANT_URL", "http://localhost:6333"),
    )
    monkeypatch.setenv(
        "OLLAMA_BASE_URL",
        os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
    )
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv(
        "FERNET_KEY", "X4O7zPlk-AbCdEfGhIjKlMnOpQrStUvWxYz0123456="
    )
    return Settings()  # type: ignore[call-arg]
