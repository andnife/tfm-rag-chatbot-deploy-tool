"""create eval_runs table

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-14 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chatbot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chatbots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dataset_path", sa.String(length=500), nullable=False),
        sa.Column("scenario_filter", sa.String(length=32), nullable=True),
        sa.Column("judge_provider", sa.String(length=32), nullable=False),
        sa.Column("judge_model", sa.String(length=128), nullable=False),
        sa.Column("judge_base_url", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("report_dir", sa.String(length=255), nullable=True),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','running','done','failed')",
            name="ck_eval_runs_status",
        ),
        sa.CheckConstraint(
            "progress BETWEEN 0 AND 100", name="ck_eval_runs_progress"
        ),
    )
    op.create_index("ix_eval_runs_tenant_id", "eval_runs", ["tenant_id"])
    op.create_index("ix_eval_runs_chatbot_id", "eval_runs", ["chatbot_id"])


def downgrade() -> None:
    op.drop_index("ix_eval_runs_chatbot_id", table_name="eval_runs")
    op.drop_index("ix_eval_runs_tenant_id", table_name="eval_runs")
    op.drop_table("eval_runs")
