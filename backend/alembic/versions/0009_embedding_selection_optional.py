"""make embedding_selection optional on knowledge_bases

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-07 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Drop the check constraint that requires embedding_selection to have 'dim' and 'model_id'
    op.execute(
        "ALTER TABLE knowledge_bases DROP CONSTRAINT IF EXISTS ck_knowledge_bases_embedding_keys"
    )
    # Make embedding_selection nullable
    op.alter_column(
        "knowledge_bases",
        "embedding_selection",
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "knowledge_bases",
        "embedding_selection",
        nullable=False,
    )
    op.execute(
        "ALTER TABLE knowledge_bases ADD CONSTRAINT ck_knowledge_bases_embedding_keys "
        "CHECK ((embedding_selection ? 'dim') AND (embedding_selection ? 'model_id'))"
    )
