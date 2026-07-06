"""provider_credentials: add nullable max_concurrency (per-credential rate limit)

Revision ID: 0023_cred_max_concurrency
Revises: 0022_kb_description_llm
Create Date: 2026-07-01

"""
from alembic import op
import sqlalchemy as sa

revision = "0023_cred_max_concurrency"
down_revision = "0022_kb_description_llm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_credentials",
        sa.Column("max_concurrency", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("provider_credentials", "max_concurrency")
