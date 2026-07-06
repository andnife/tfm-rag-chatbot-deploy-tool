"""eval_runs: drop cost calculator columns

Removes the monetary cost-estimation columns from ``eval_runs``:
``prices_snapshot`` (JSONB), ``est_cost`` (Float) and ``actual_cost`` (Float).
The raw token-count columns (tokens_gen_in/out, tokens_judge_in/out) are kept —
they are accurate telemetry, not the cost calculator being removed.

Revision ID: 0025_eval_runs_drop_cost
Revises: 0024_cred_min_interval
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0025_eval_runs_drop_cost"
down_revision = "0024_cred_min_interval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("eval_runs", "actual_cost")
    op.drop_column("eval_runs", "est_cost")
    op.drop_column("eval_runs", "prices_snapshot")


def downgrade() -> None:
    op.add_column(
        "eval_runs",
        sa.Column("prices_snapshot", JSONB, nullable=True),
    )
    op.add_column(
        "eval_runs",
        sa.Column("est_cost", sa.Float(), nullable=True),
    )
    op.add_column(
        "eval_runs",
        sa.Column("actual_cost", sa.Float(), nullable=True),
    )
