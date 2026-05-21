"""create knowledge_bases and sources tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-21 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("chunking_config", postgresql.JSONB(), nullable=False),
        sa.Column("embedding_selection", postgresql.JSONB(), nullable=False),
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
            "tenant_id", "name",
            name="uq_knowledge_bases_tenant_name",
        ),
        sa.CheckConstraint(
            "(embedding_selection ? 'dim') AND (embedding_selection ? 'model_id')",
            name="ck_knowledge_bases_embedding_keys",
        ),
    )
    op.create_index(
        "ix_knowledge_bases_tenant_id", "knowledge_bases", ["tenant_id"]
    )

    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "kb_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "ingest_status",
            sa.String(length=16),
            nullable=False,
            server_default="not_started",
        ),
        sa.Column("last_ingest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.CheckConstraint(
            "type IN ('document','database')",
            name="ck_sources_type",
        ),
        sa.CheckConstraint(
            "ingest_status IN ('not_started','queued','running','done','failed')",
            name="ck_sources_ingest_status",
        ),
    )
    op.create_index("ix_sources_kb_id", "sources", ["kb_id"])
    op.create_index("ix_sources_kb_id_type", "sources", ["kb_id", "type"])


def downgrade() -> None:
    op.drop_index("ix_sources_kb_id_type", table_name="sources")
    op.drop_index("ix_sources_kb_id", table_name="sources")
    op.drop_table("sources")
    op.drop_index("ix_knowledge_bases_tenant_id", table_name="knowledge_bases")
    op.drop_table("knowledge_bases")
