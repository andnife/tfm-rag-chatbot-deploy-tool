"""Add public_key column to chatbots.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-25
"""
import secrets
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Step 1: add as nullable so we can backfill existing rows (if any).
    op.add_column(
        "chatbots",
        sa.Column("public_key", sa.String(length=64), nullable=True),
    )

    # Step 2: backfill any existing rows with random unique values.
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id FROM chatbots WHERE public_key IS NULL")
    ).fetchall()
    for row in rows:
        chatbot_id = row[0]
        conn.execute(
            sa.text(
                "UPDATE chatbots SET public_key = :pk WHERE id = :id"
            ),
            {"pk": "wgt_" + secrets.token_urlsafe(32), "id": chatbot_id},
        )

    # Step 3: enforce NOT NULL + UNIQUE.
    op.alter_column("chatbots", "public_key", nullable=False)
    op.create_unique_constraint(
        "uq_chatbots_public_key", "chatbots", ["public_key"]
    )
    op.create_index(
        "ix_chatbots_public_key", "chatbots", ["public_key"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_chatbots_public_key", table_name="chatbots")
    op.drop_constraint("uq_chatbots_public_key", "chatbots", type_="unique")
    op.drop_column("chatbots", "public_key")
