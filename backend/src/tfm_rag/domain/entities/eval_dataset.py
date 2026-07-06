"""Domain entities for evaluation datasets and their rows.

`EvalDataset` / `EvalDatasetItem` are the persistence-facing aggregates
(mapped from the ORM rows by the concrete repository). `EvalDatasetItemInput`
is the write-side input the use case hands to the repo when replacing a
dataset's rows (ordinal + ids are assigned by the repo).
"""
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

DatasetStatus = Literal["draft", "processing", "ready", "failed"]


@dataclass(frozen=True, slots=True)
class EvalDataset:
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    knowledge_base_id: UUID | None
    db_schema_name: str | None
    sql_seed_artifact: str | None
    status: DatasetStatus
    status_error: str | None


@dataclass(frozen=True, slots=True)
class EvalDatasetItem:
    id: UUID
    tenant_id: UUID
    dataset_id: UUID
    ordinal: int
    question: str
    ground_truth: str
    scenario: str
    complexity: str
    reference_contexts: list[str] | None
    sql_reference: str | None
    source_doc: str | None


@dataclass(frozen=True, slots=True)
class EvalDatasetItemInput:
    """A validated, ready-to-persist dataset row (ordinal/id assigned by repo)."""

    question: str
    ground_truth: str
    scenario: str
    complexity: str
    reference_contexts: list[str] | None
    sql_reference: str | None
    source_doc: str | None
