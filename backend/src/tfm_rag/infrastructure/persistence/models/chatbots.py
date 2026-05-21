from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from tfm_rag.infrastructure.persistence.base import Base


class ChatbotRow(Base):
    __tablename__ = "chatbots"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "name",
            name="uq_chatbots_tenant_name",
        ),
        # Spec §9: invariant on max_retrieval_iterations
        CheckConstraint(
            "((pipeline_config->>'max_retrieval_iterations')::int "
            "BETWEEN 1 AND 5)",
            name="ck_chatbots_max_retrieval_iterations",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    system_prompt: Mapped[str] = mapped_column(String(8000), nullable=False)
    llm_selection: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    router_llm_selection: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    pipeline_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    widget_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
