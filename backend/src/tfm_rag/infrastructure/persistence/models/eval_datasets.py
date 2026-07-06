from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from tfm_rag.infrastructure.persistence.base import Base


class EvalDatasetRow(Base):
    __tablename__ = "eval_datasets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_eval_datasets_tenant_name"),
        CheckConstraint(
            "status IN ('draft','processing','ready','failed')",
            name="ck_eval_datasets_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    knowledge_base_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    db_schema_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sql_seed_artifact: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="draft"
    )
    status_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class EvalDatasetItemRow(Base):
    __tablename__ = "eval_dataset_rows"
    __table_args__ = (
        CheckConstraint(
            "scenario IN ('doc_only','sql_only','mixed','abstain')",
            name="ck_eval_dataset_rows_scenario",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("eval_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(String(2000), nullable=False)
    ground_truth: Mapped[str] = mapped_column(String(4000), nullable=False)
    scenario: Mapped[str] = mapped_column(String(16), nullable=False)
    complexity: Mapped[str] = mapped_column(String(16), nullable=False)
    reference_contexts: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    sql_reference: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    source_doc: Mapped[str | None] = mapped_column(String(500), nullable=True)
