"""eval_runs: drop judge_provider and judge_base_url columns

Revision ID: 0021_drop_judge_cols
Revises: 0020_eval_runs_judge_credential
"""
import sqlalchemy as sa
from alembic import op

revision = "0021_drop_judge_cols"
down_revision = "0020_eval_runs_judge_credential"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("eval_runs", "judge_provider")
    op.drop_column("eval_runs", "judge_base_url")


def downgrade() -> None:
    op.add_column(
        "eval_runs",
        sa.Column(
            "judge_base_url",
            sa.String(500),
            nullable=True,
        ),
    )
    op.add_column(
        "eval_runs",
        sa.Column(
            "judge_provider",
            sa.String(32),
            nullable=True,
            server_default="ollama",
        ),
    )
    # Make NOT NULL after backfill (all existing rows will get the server_default)
    op.alter_column("eval_runs", "judge_provider", nullable=False, server_default=None)
