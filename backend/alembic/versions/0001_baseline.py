"""baseline

Revision ID: 0001
Revises:
Create Date: 2026-05-20 00:00:00.000000

This migration creates no tables yet — it's the empty baseline against
which all subsequent CAP migrations apply.
"""
from __future__ import annotations

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Baseline — no schema changes."""
    pass


def downgrade() -> None:
    """Baseline — no schema changes."""
    pass
