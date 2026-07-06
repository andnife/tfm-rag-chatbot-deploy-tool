from functools import lru_cache
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import Field, field_validator
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
    # Connection pool sizing. Total usable connections = db_pool_size +
    # db_max_overflow. This total is the single source of truth for how much
    # concurrency the eval runner will use: it auto-clamps its per-case
    # generation concurrency to (total - API reserve) and the cases queue on a
    # semaphore, so a credential's max_concurrency is honoured up to this ceiling
    # and simply *waits its turn* beyond it — it never overflows the pool and
    # breaks. Raise a credential toward the ceiling and it "just works" with no
    # DB change. To go past the ceiling, raise these two values (and, if needed,
    # the Postgres server's max_connections — default 100 — which is the real
    # hard limit this total must stay under).
    db_pool_size: int = 20
    db_max_overflow: int = 60
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
    # httpOnly auth cookie: Secure flag on in production (HTTPS). Off in dev.
    cookie_secure: bool = False
    fernet_key: str = Field(..., min_length=32)

    @field_validator("fernet_key")
    @classmethod
    def _validate_fernet_key(cls, value: str) -> str:
        """Fail fast at startup with a clear error.

        `min_length=32` alone lets through strings that are the right
        length but not valid url-safe-base64-encoded 32-byte keys (e.g. a
        pasted JWT secret). Without this, the app boots fine and then
        every credential encrypt/decrypt call blows up with a cryptic
        `cryptography` error deep in a request.
        """
        try:
            Fernet(value.encode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - re-raised with a clear message
            raise ValueError(
                "fernet_key is not a valid Fernet key (must be 32 url-safe "
                "base64-encoded bytes, e.g. Fernet.generate_key()); "
                f"underlying error: {exc}"
            ) from exc
        return value

    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    # Storage
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_path: str = "/data/storage"
    storage_s3_bucket: str | None = None
    storage_s3_region: str | None = None
    # Eval-dataset SQL provisioning (admin connection to the test MySQL).
    eval_mysql_host: str = "localhost"
    eval_mysql_port: int = 3306
    eval_mysql_admin_user: str = "root"
    eval_mysql_admin_password: str = "rootpw"  # noqa: S105 - local dev default, env-overridable
    # Misc
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # Comma-separated list of origins allowed to call the authenticated API
    # surface (app-level CORS). The public widget endpoints (`/api/public/*`)
    # are governed separately, per-chatbot — see
    # `infrastructure.api.middleware.widget_cors.PathScopedCORSMiddleware`.
    frontend_origin: str = "http://localhost:3000"
    # In-process token-bucket limits for the unauthenticated public widget
    # chat endpoint. See `infrastructure.api.rate_limiting` for the
    # multi-worker caveat (state is per-process, not shared/distributed).
    public_chat_rate_per_minute: int = 20
    public_chat_burst: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg,unused-ignore]
