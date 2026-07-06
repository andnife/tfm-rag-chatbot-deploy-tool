"""pipeline_config: self-correction retries (drop agentic_mode + iterations)

Replaces the reactive agent-loop config with the explicit router's config:
- removes `agentic_mode` and `max_retrieval_iterations` from chatbots.pipeline_config
- adds `max_self_correction_retries` = 1
- swaps the CHECK constraint accordingly

Revision ID: 0013
Revises: 0012
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_chatbots_max_retrieval_iterations", "chatbots", type_="check"
    )
    op.execute(
        """
        UPDATE chatbots
        SET pipeline_config =
            (pipeline_config - 'agentic_mode' - 'max_retrieval_iterations')
            || jsonb_build_object('max_self_correction_retries', 1)
        """
    )
    op.create_check_constraint(
        "ck_chatbots_max_self_correction_retries",
        "chatbots",
        "((pipeline_config->>'max_self_correction_retries')::int BETWEEN 0 AND 3)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_chatbots_max_self_correction_retries", "chatbots", type_="check"
    )
    op.execute(
        """
        UPDATE chatbots
        SET pipeline_config =
            (pipeline_config - 'max_self_correction_retries')
            || jsonb_build_object('agentic_mode', true,
                                  'max_retrieval_iterations', 3)
        """
    )
    op.create_check_constraint(
        "ck_chatbots_max_retrieval_iterations",
        "chatbots",
        "((pipeline_config->>'max_retrieval_iterations')::int BETWEEN 1 AND 5)",
    )
