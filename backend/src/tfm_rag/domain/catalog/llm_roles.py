"""Catalog of LLM *roles* a chatbot can map to distinct models.

Single source of truth for the role-name strings used by per-role LLM
selection (sub-proyecto A) and consumed by the router (sub-proyecto B).
"""

ROLE_EVALUATOR = "evaluator"
ROLE_SQL_GENERATOR = "sql_generator"
ROLE_ANSWER_GENERATOR = "answer_generator"

ROLE_NAMES: tuple[str, ...] = (
    ROLE_EVALUATOR,
    ROLE_SQL_GENERATOR,
    ROLE_ANSWER_GENERATOR,
)
