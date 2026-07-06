"""provider_credentials: add nullable min_request_interval_seconds (rate spacing)

Revision ID: 0024_cred_min_interval
Revises: 0023_cred_max_concurrency
Create Date: 2026-07-01

"""
from alembic import op
import sqlalchemy as sa

revision = "0024_cred_min_interval"
down_revision = "0023_cred_max_concurrency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_credentials",
        sa.Column("min_request_interval_seconds", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("provider_credentials", "min_request_interval_seconds")
