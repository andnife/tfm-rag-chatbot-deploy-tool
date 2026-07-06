"""Load an eval dataset from DB entity rows into EvaluationCase objects."""
from __future__ import annotations

from uuid import UUID

from tfm_rag.domain.ports.repositories import (
    EvalDatasetItemRepositoryPort,
    EvalDatasetRepositoryPort,
)
from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase


async def load_eval_dataset_from_db(
    *,
    ds_repo: EvalDatasetRepositoryPort,
    item_repo: EvalDatasetItemRepositoryPort,
    dataset_id: UUID,
    scenario_filter: str | None = None,
) -> tuple[list[EvaluationCase], UUID | None]:
    """Load dataset rows from DB and return (cases, knowledge_base_id).

    Args:
        ds_repo: Eval-dataset repository port (tenant-scoped).
        item_repo: Eval-dataset-item repository port (tenant-scoped).
        dataset_id: UUID of the dataset to load.
        scenario_filter: If given, only cases whose ``scenario`` matches are
            included. ``None`` means no filtering.

    Returns:
        A tuple of (list[EvaluationCase], knowledge_base_id | None).
    """
    dataset = await ds_repo.get_dataset(dataset_id)
    items = await item_repo.list_items_by_dataset(dataset_id)

    cases: list[EvaluationCase] = []
    for item in items:
        if scenario_filter and item.scenario != scenario_filter:
            continue
        cases.append(
            EvaluationCase(
                question=item.question,
                ground_truth=item.ground_truth,
                scenario=item.scenario,
                metadata={
                    "complexity": item.complexity,
                    "reference_contexts": item.reference_contexts or [],
                    "sql_reference": item.sql_reference,
                    "source_doc": item.source_doc,
                },
            )
        )

    return cases, dataset.knowledge_base_id
