"""eval_runs dataset_id + token/cost columns

Adds `dataset_id` (FK → eval_datasets, nullable), `prices_snapshot` (JSONB),
`tokens_gen_in`/`tokens_gen_out`/`tokens_judge_in`/`tokens_judge_out` (Integer),
`est_cost`/`actual_cost` (Float). Also makes `dataset_path` nullable so entity
runs without a file path can be created.

Revision ID: 0017
Revises: 0016
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_runs",
        sa.Column(
            "dataset_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("eval_datasets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_eval_runs_dataset_id", "eval_runs", ["dataset_id"])

    op.add_column(
        "eval_runs",
        sa.Column("prices_snapshot", JSONB, nullable=True),
    )
    op.add_column(
        "eval_runs",
        sa.Column("tokens_gen_in", sa.Integer(), nullable=True),
    )
    op.add_column(
        "eval_runs",
        sa.Column("tokens_gen_out", sa.Integer(), nullable=True),
    )
    op.add_column(
        "eval_runs",
        sa.Column("tokens_judge_in", sa.Integer(), nullable=True),
    )
    op.add_column(
        "eval_runs",
        sa.Column("tokens_judge_out", sa.Integer(), nullable=True),
    )
    op.add_column(
        "eval_runs",
        sa.Column("est_cost", sa.Float(), nullable=True),
    )
    op.add_column(
        "eval_runs",
        sa.Column("actual_cost", sa.Float(), nullable=True),
    )

    # Make dataset_path nullable — entity runs (driven by eval_datasets) have no file path
    op.alter_column("eval_runs", "dataset_path", nullable=True)


def downgrade() -> None:
    op.alter_column("eval_runs", "dataset_path", nullable=False)

    op.drop_column("eval_runs", "actual_cost")
    op.drop_column("eval_runs", "est_cost")
    op.drop_column("eval_runs", "tokens_judge_out")
    op.drop_column("eval_runs", "tokens_judge_in")
    op.drop_column("eval_runs", "tokens_gen_out")
    op.drop_column("eval_runs", "tokens_gen_in")
    op.drop_column("eval_runs", "prices_snapshot")

    op.drop_index("ix_eval_runs_dataset_id", table_name="eval_runs")
    op.drop_column("eval_runs", "dataset_id")
