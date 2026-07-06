"""ingestion_jobs: stage + item counters for granular progress

Adds nullable `stage`, `items_done`, `items_total` columns to `ingestion_jobs`
so the UI can render a per-phase progress bar (extracting/chunking/embedding/
indexing) with a real chunk counter. NULL = no phase info (older rows / coarse
progress only).

Revision ID: 0015
Revises: 0014
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ingestion_jobs", sa.Column("stage", sa.String(length=16), nullable=True)
    )
    op.add_column(
        "ingestion_jobs", sa.Column("items_done", sa.Integer(), nullable=True)
    )
    op.add_column(
        "ingestion_jobs", sa.Column("items_total", sa.Integer(), nullable=True)
    )
    op.create_check_constraint(
        "ck_ingestion_jobs_stage",
        "ingestion_jobs",
        "stage IS NULL OR stage IN "
        "('extracting','chunking','embedding','indexing')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_ingestion_jobs_stage", "ingestion_jobs", type_="check")
    op.drop_column("ingestion_jobs", "items_total")
    op.drop_column("ingestion_jobs", "items_done")
    op.drop_column("ingestion_jobs", "stage")
