"""create provider_credentials table

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-20 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_id", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("api_key_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("config_source", sa.String(length=32), nullable=False),
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
            "tenant_id", "provider_id", "label",
            name="uq_provider_credentials_tenant_provider_label",
        ),
        sa.CheckConstraint(
            "config_source IN ('SERVER_ENV','TENANT_CREDENTIAL')",
            name="ck_provider_credentials_config_source",
        ),
    )
    op.create_index(
        "ix_provider_credentials_tenant_id",
        "provider_credentials",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_provider_credentials_tenant_id", table_name="provider_credentials"
    )
    op.drop_table("provider_credentials")
