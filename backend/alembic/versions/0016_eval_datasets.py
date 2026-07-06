"""eval datasets as first-class entities

Adds `eval_datasets` (1:1 with a dedicated knowledge base) and
`eval_dataset_rows` (the Q/A rows). Replaces loose-JSONL datasets.

Revision ID: 0016
Revises: 0015
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_datasets",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id", PG_UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("knowledge_base_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("db_schema_name", sa.String(128), nullable=True),
        sa.Column("sql_seed_artifact", sa.String(500), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("status_error", sa.String(2000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_eval_datasets_tenant_name"),
        sa.CheckConstraint(
            "status IN ('draft','processing','ready','failed')",
            name="ck_eval_datasets_status",
        ),
    )
    op.create_index(
        "ix_eval_datasets_tenant_id", "eval_datasets", ["tenant_id"]
    )

    op.create_table(
        "eval_dataset_rows",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id", PG_UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "dataset_id", PG_UUID(as_uuid=True),
            sa.ForeignKey("eval_datasets.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("question", sa.String(2000), nullable=False),
        sa.Column("ground_truth", sa.String(4000), nullable=False),
        sa.Column("scenario", sa.String(16), nullable=False),
        sa.Column("complexity", sa.String(16), nullable=False),
        sa.Column("reference_contexts", JSONB, nullable=True),
        sa.Column("sql_reference", sa.String(4000), nullable=True),
        sa.Column("source_doc", sa.String(500), nullable=True),
        sa.CheckConstraint(
            "scenario IN ('doc_only','sql_only','mixed','abstain')",
            name="ck_eval_dataset_rows_scenario",
        ),
    )
    op.create_index(
        "ix_eval_dataset_rows_tenant_id", "eval_dataset_rows", ["tenant_id"]
    )
    op.create_index(
        "ix_eval_dataset_rows_dataset_id", "eval_dataset_rows", ["dataset_id"]
    )


def downgrade() -> None:
    op.drop_table("eval_dataset_rows")
    op.drop_table("eval_datasets")
