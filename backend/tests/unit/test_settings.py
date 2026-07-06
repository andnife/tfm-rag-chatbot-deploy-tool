import pytest

from tfm_rag.infrastructure.settings import Settings


def test_settings_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://u:p@h:5432/d")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("FERNET_KEY", "qjd374RRcCpzdVhmmLHCnjxvBfrFwbwErhxIj4nq_XM=")

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


def test_public_chat_rate_limit_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://u:p@h:5432/d")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("FERNET_KEY", "qjd374RRcCpzdVhmmLHCnjxvBfrFwbwErhxIj4nq_XM=")

    s = Settings()  # type: ignore[call-arg]

    assert s.public_chat_rate_per_minute == 20
    assert s.public_chat_burst == 5


def test_rate_limit_redis_url_setting_removed() -> None:
    assert "rate_limit_redis_url" not in Settings.model_fields


def test_fernet_key_must_be_a_valid_fernet_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task 4 (T16): fail fast at startup with a clear error, instead of a
    cryptic failure the first time a credential secret is encrypted/decrypted.
    """
    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://u:p@h:5432/d")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    # 32 chars but NOT valid url-safe base64 encoding 32 raw bytes.
    monkeypatch.setenv("FERNET_KEY", "y" * 32)

    with pytest.raises(Exception, match="(?i)fernet"):  # noqa: B017
        Settings()  # type: ignore[call-arg]
