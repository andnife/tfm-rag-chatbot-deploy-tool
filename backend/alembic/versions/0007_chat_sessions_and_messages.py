"""create chat_sessions and chat_messages tables

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-21 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "chatbot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chatbots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("public_session_cookie", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "origin IN ('playground','widget')",
            name="ck_chat_sessions_origin",
        ),
    )
    op.create_index("ix_chat_sessions_chatbot_id", "chat_sessions", ["chatbot_id"])
    op.create_index("ix_chat_sessions_tenant_id", "chat_sessions", ["tenant_id"])
    op.create_index(
        "ix_chat_sessions_public_session_cookie",
        "chat_sessions",
        ["public_session_cookie"],
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "citations",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('user','assistant','system')",
            name="ck_chat_messages_role",
        ),
    )
    op.create_index(
        "ix_chat_messages_session_id_created_at",
        "chat_messages",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chat_messages_session_id_created_at",
        table_name="chat_messages",
    )
    op.drop_table("chat_messages")
    op.drop_index(
        "ix_chat_sessions_public_session_cookie",
        table_name="chat_sessions",
    )
    op.drop_index(
        "ix_chat_sessions_tenant_id", table_name="chat_sessions"
    )
    op.drop_index(
        "ix_chat_sessions_chatbot_id", table_name="chat_sessions"
    )
    op.drop_table("chat_sessions")
