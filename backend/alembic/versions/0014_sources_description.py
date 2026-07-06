"""sources: per-document auto-generated description (sub-proyecto C1)

Adds a nullable `description` column to `sources`, filled best-effort at
ingestion from the document's chunks. NULL = no description (router falls
back to the filename).

Revision ID: 0014
Revises: 0013
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("description", sa.String(length=2000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sources", "description")
