from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from tfm_rag.infrastructure.persistence.base import Base


class SourceRow(Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint(
            "type IN ('document','database')",
            name="ck_sources_type",
        ),
        CheckConstraint(
            "ingest_status IN ('not_started','queued','running','done','failed')",
            name="ck_sources_ingest_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    kb_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ingest_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="not_started"
    )
    last_ingest_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
