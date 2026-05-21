"""create ingestion_jobs table

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-21 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "progress", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "finished_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','done','failed')",
            name="ck_ingestion_jobs_status",
        ),
        sa.CheckConstraint(
            "progress BETWEEN 0 AND 100",
            name="ck_ingestion_jobs_progress",
        ),
    )
    op.create_index(
        "ix_ingestion_jobs_source_id", "ingestion_jobs", ["source_id"]
    )
    op.create_index(
        "ix_ingestion_jobs_tenant_id", "ingestion_jobs", ["tenant_id"]
    )
    op.create_index(
        "ix_ingestion_jobs_status", "ingestion_jobs", ["status"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ingestion_jobs_status", table_name="ingestion_jobs"
    )
    op.drop_index(
        "ix_ingestion_jobs_tenant_id", table_name="ingestion_jobs"
    )
    op.drop_index(
        "ix_ingestion_jobs_source_id", table_name="ingestion_jobs"
    )
    op.drop_table("ingestion_jobs")
