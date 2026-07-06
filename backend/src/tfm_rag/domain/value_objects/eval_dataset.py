from dataclasses import dataclass
from uuid import UUID

from tfm_rag.domain.catalog.eval_scenarios import (
    SCENARIO_SQL_ONLY,
    is_known_scenario,
)
from tfm_rag.domain.errors.evaluation import EvalDatasetError

DATASET_STATUSES: frozenset[str] = frozenset(
    {"draft", "processing", "ready", "failed"}
)
KNOWN_COMPLEXITIES: frozenset[str] = frozenset(
    {"factual", "inferencial", "comparativa"}
)

_MIN_QUESTION_LEN = 5


def validate_row_fields(
    *,
    question: str,
    ground_truth: str,
    scenario: str,
    complexity: str,
    sql_reference: str | None,
) -> None:
    if len(question.strip()) < _MIN_QUESTION_LEN:
        raise EvalDatasetError(
            f"question must be at least {_MIN_QUESTION_LEN} chars"
        )
    if not ground_truth.strip():
        raise EvalDatasetError("ground_truth must not be empty")
    if not is_known_scenario(scenario):
        raise EvalDatasetError(f"unknown scenario {scenario!r}")
    if complexity not in KNOWN_COMPLEXITIES:
        raise EvalDatasetError(f"unknown complexity {complexity!r}")
    if scenario == SCENARIO_SQL_ONLY and not (sql_reference or "").strip():
        raise EvalDatasetError("sql_only rows require a sql_reference")


@dataclass(frozen=True, slots=True)
class EvalDatasetRowView:
    id: UUID
    dataset_id: UUID
    ordinal: int
    question: str
    ground_truth: str
    scenario: str
    complexity: str
    reference_contexts: list[str]
    sql_reference: str | None
    source_doc: str | None


@dataclass(frozen=True, slots=True)
class EvalDatasetView:
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    knowledge_base_id: UUID | None
    db_schema_name: str | None
    sql_seed_artifact: str | None
    status: str
    status_error: str | None
    num_rows: int
