from tfm_rag.infrastructure.persistence.models.eval_datasets import (
    EvalDatasetItemRow,
    EvalDatasetRow,
)


def test_eval_dataset_tablenames() -> None:
    assert EvalDatasetRow.__tablename__ == "eval_datasets"
    assert EvalDatasetItemRow.__tablename__ == "eval_dataset_rows"


def test_eval_dataset_row_has_expected_columns() -> None:
    cols = set(EvalDatasetRow.__table__.columns.keys())
    assert {
        "id", "tenant_id", "name", "description", "knowledge_base_id",
        "db_schema_name", "sql_seed_artifact", "status", "status_error",
        "created_at", "updated_at",
    } <= cols


def test_eval_dataset_item_row_has_tenant_and_dataset_fk() -> None:
    cols = set(EvalDatasetItemRow.__table__.columns.keys())
    assert {
        "id", "tenant_id", "dataset_id", "ordinal", "question",
        "ground_truth", "scenario", "complexity", "reference_contexts",
        "sql_reference", "source_doc",
    } <= cols
