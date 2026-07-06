from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from tfm_rag.infrastructure.persistence.base import Base


class ProviderCredentialRow(Base):
    __tablename__ = "provider_credentials"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider_id", "label",
            name="uq_provider_credentials_tenant_provider_label",
        ),
        CheckConstraint(
            "config_source IN ('SERVER_ENV','TENANT_CREDENTIAL')",
            name="ck_provider_credentials_config_source",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_id: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    config_source: Mapped[str] = mapped_column(String(32), nullable=False)
    # Optional per-credential concurrency cap for outbound calls to this
    # provider (its rate limit). Consumed by the eval run to size RAGAS'
    # max_workers so a rate-limited judge endpoint isn't stormed. NULL = unset
    # (callers fall back to their default / env).
    max_concurrency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Optional minimum spacing between outbound requests, in seconds (e.g. 2.0 =
    # at most one request every 2s → ~30/min). Applied to the eval judge via a
    # LangChain InMemoryRateLimiter (requests_per_second = 1/interval). NULL = none.
    min_request_interval_seconds: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
