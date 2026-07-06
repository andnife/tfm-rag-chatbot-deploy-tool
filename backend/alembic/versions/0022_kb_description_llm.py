"""knowledge_bases: add description_llm (nullable ModelRef JSONB)

Revision ID: 0022_kb_description_llm
Revises: 0021_drop_judge_cols
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0022_kb_description_llm"
down_revision = "0021_drop_judge_cols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column("description_llm", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_bases", "description_llm")
