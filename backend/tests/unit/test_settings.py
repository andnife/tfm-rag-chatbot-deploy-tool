import pytest

from tfm_rag.infrastructure.settings import Settings


def test_settings_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://u:p@h:5432/d")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("FERNET_KEY", "X4O7zPlk-AbCdEfGhIjKlMnOpQrStUvWxYz0123456=")

    s = Settings()  # type: ignore[call-arg]

    assert s.postgres_url == "postgresql+asyncpg://u:p@h:5432/d"
    assert s.qdrant_url == "http://qdrant:6333"
    assert s.ollama_base_url == "http://ollama:11434"
    assert s.jwt_expires_hours == 24
    assert s.log_level == "INFO"


def test_settings_missing_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("POSTGRES_URL", "QDRANT_URL", "OLLAMA_BASE_URL", "JWT_SECRET", "FERNET_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(Exception):  # pydantic ValidationError  # noqa: B017
        Settings()  # type: ignore[call-arg]
