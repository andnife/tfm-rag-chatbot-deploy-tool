"""eval_runs: add nullable judge_credential_id column

Revision ID: 0020_eval_runs_judge_credential
Revises: 0019_eval_runs_cancelled_status
"""
import sqlalchemy as sa
from alembic import op

revision = "0020_eval_runs_judge_credential"
down_revision = "0019_eval_runs_cancelled_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "eval_runs",
        sa.Column("judge_credential_id", sa.UUID(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("eval_runs", "judge_credential_id")
