"""drop vestigial chatbots.router_llm_selection column

A chatbot uses a single LLM (`llm_selection`) for everything — query routing,
RAG generation, etc. The separate `router_llm_selection` was never consumed by
the runtime and contradicted that design, so it is removed.

Revision ID: 0011
Revises: 0010
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("chatbots", "router_llm_selection")


def downgrade() -> None:
    op.add_column(
        "chatbots",
        sa.Column(
            "router_llm_selection", postgresql.JSONB(), nullable=True
        ),
    )
