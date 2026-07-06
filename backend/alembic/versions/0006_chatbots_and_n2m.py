"""create chatbots and chatbot_knowledge_base tables

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-21 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chatbots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("system_prompt", sa.String(length=8000), nullable=False),
        sa.Column("llm_selection", postgresql.JSONB(), nullable=False),
        sa.Column("router_llm_selection", postgresql.JSONB(), nullable=True),
        sa.Column("pipeline_config", postgresql.JSONB(), nullable=False),
        sa.Column("widget_config", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "name", name="uq_chatbots_tenant_name"
        ),
        sa.CheckConstraint(
            "((pipeline_config->>'max_retrieval_iterations')::int "
            "BETWEEN 1 AND 5)",
            name="ck_chatbots_max_retrieval_iterations",
        ),
    )
    op.create_index("ix_chatbots_tenant_id", "chatbots", ["tenant_id"])

    op.create_table(
        "chatbot_knowledge_base",
        sa.Column(
            "chatbot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chatbots.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "kb_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_chatbot_knowledge_base_kb_id",
        "chatbot_knowledge_base",
        ["kb_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chatbot_knowledge_base_kb_id",
        table_name="chatbot_knowledge_base",
    )
    op.drop_table("chatbot_knowledge_base")
    op.drop_index("ix_chatbots_tenant_id", table_name="chatbots")
    op.drop_table("chatbots")
