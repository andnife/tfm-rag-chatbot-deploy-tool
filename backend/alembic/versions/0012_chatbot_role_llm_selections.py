"""add chatbots.role_llm_selections (per-role LLM config)

Generalised per-role LLM selection map. Where 0011 dropped the vestigial
single `router_llm_selection`, this adds a map keyed by role
(evaluator / sql_generator / answer_generator). Default '{}' means every
role falls back to the chatbot's main `llm_selection`.

Revision ID: 0012
Revises: 0011
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chatbots",
        sa.Column(
            "role_llm_selections",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("chatbots", "role_llm_selections")
