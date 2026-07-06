"""eval_runs: allow 'cancelled' status

Revision ID: 0019_eval_runs_cancelled_status
Revises: 0018
"""
from alembic import op

revision = "0019_eval_runs_cancelled_status"
down_revision = "0018"
branch_labels = None
depends_on = None

_OLD = "status IN ('queued','running','done','failed')"
_NEW = "status IN ('queued','running','done','failed','cancelled')"


def upgrade() -> None:
    op.drop_constraint("ck_eval_runs_status", "eval_runs", type_="check")
    op.create_check_constraint("ck_eval_runs_status", "eval_runs", _NEW)


def downgrade() -> None:
    op.drop_constraint("ck_eval_runs_status", "eval_runs", type_="check")
    op.create_check_constraint("ck_eval_runs_status", "eval_runs", _OLD)
