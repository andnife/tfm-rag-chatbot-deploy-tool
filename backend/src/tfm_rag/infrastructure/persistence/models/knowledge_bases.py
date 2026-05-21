from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from tfm_rag.infrastructure.persistence.base import Base


class KnowledgeBaseRow(Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "name",
            name="uq_knowledge_bases_tenant_name",
        ),
        CheckConstraint(
            "(embedding_selection ? 'dim') AND (embedding_selection ? 'model_id')",
            name="ck_knowledge_bases_embedding_keys",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        # FK declared in migration; column is also defined here for ORM use.
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    chunking_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    embedding_selection: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
