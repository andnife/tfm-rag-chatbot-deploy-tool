from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    postgres_url: str = Field(...)
    # Qdrant
    qdrant_url: str = Field(...)
    qdrant_api_key: str | None = None
    # Ollama
    ollama_base_url: str = Field(...)
    ollama_default_llm_model: str = "llama3.1"
    ollama_default_embedding_model: str = "bge-m3"
    # Auth
    jwt_secret: str = Field(..., min_length=32)
    jwt_expires_hours: int = 24
    fernet_key: str = Field(..., min_length=32)
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    # Storage
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_path: str = "/data/storage"
    storage_s3_bucket: str | None = None
    storage_s3_region: str | None = None
    # Misc
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    rate_limit_redis_url: str | None = None
    frontend_origin: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg,unused-ignore]
