from tfm_rag.infrastructure.persistence.models.eval_runs import EvalRunRow


def test_eval_run_row_table_and_columns() -> None:
    assert EvalRunRow.__tablename__ == "eval_runs"
    cols = set(EvalRunRow.__table__.columns.keys())
    assert {
        "id", "tenant_id", "chatbot_id", "dataset_path", "scenario_filter",
        "judge_model", "judge_credential_id",
        "status", "progress", "report_dir", "error", "created_at", "started_at",
        "finished_at",
    } <= cols
    # judge_provider and judge_base_url are removed in migration 0021
    assert "judge_provider" not in cols
    assert "judge_base_url" not in cols
