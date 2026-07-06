from uuid import uuid4

import pytest

from tfm_rag.domain.errors.evaluation import EvalDatasetError
from tfm_rag.domain.value_objects.eval_dataset import (
    DATASET_STATUSES,
    KNOWN_COMPLEXITIES,
    EvalDatasetRowView,
    EvalDatasetView,
    validate_row_fields,
)


def test_validate_row_fields_accepts_valid_doc_row() -> None:
    validate_row_fields(
        question="¿Cuántos años de garantía?",
        ground_truth="3 años",
        scenario="doc_only",
        complexity="factual",
        sql_reference=None,
    )


def test_validate_row_fields_rejects_short_question() -> None:
    with pytest.raises(EvalDatasetError):
        validate_row_fields(
            question="hi", ground_truth="x", scenario="doc_only",
            complexity="factual", sql_reference=None,
        )


def test_validate_row_fields_rejects_unknown_scenario() -> None:
    with pytest.raises(EvalDatasetError):
        validate_row_fields(
            question="¿pregunta larga válida?", ground_truth="x",
            scenario="nonsense", complexity="factual", sql_reference=None,
        )


def test_validate_row_fields_requires_sql_reference_for_sql_only() -> None:
    with pytest.raises(EvalDatasetError):
        validate_row_fields(
            question="¿cuántos pedidos hay?", ground_truth="5",
            scenario="sql_only", complexity="factual", sql_reference=None,
        )


def test_views_are_constructible() -> None:
    row = EvalDatasetRowView(
        id=uuid4(), dataset_id=uuid4(), ordinal=0, question="q?" * 3,
        ground_truth="a", scenario="doc_only", complexity="factual",
        reference_contexts=[], sql_reference=None, source_doc="manual.md",
    )
    ds = EvalDatasetView(
        id=uuid4(), tenant_id=uuid4(), name="d", description=None,
        knowledge_base_id=uuid4(), db_schema_name=None, sql_seed_artifact=None,
        status="draft", status_error=None, num_rows=1,
    )
    assert row.scenario == "doc_only"
    assert ds.status in DATASET_STATUSES
    assert "factual" in KNOWN_COMPLEXITIES
