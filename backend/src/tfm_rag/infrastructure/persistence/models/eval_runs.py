from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from tfm_rag.infrastructure.persistence.base import Base


class EvalRunRow(Base):
    __tablename__ = "eval_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','done','failed','cancelled')",
            name="ck_eval_runs_status",
        ),
        CheckConstraint(
            "progress BETWEEN 0 AND 100",
            name="ck_eval_runs_progress",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chatbot_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chatbots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("eval_datasets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    dataset_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scenario_filter: Mapped[str | None] = mapped_column(String(32), nullable=True)
    judge_model: Mapped[str] = mapped_column(String(128), nullable=False)
    judge_credential_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    report_dir: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    tokens_gen_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_gen_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_judge_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_judge_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
