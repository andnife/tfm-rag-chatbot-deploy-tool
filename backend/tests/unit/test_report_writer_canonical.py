from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from tfm_rag.application.evaluation.report_writer import write_report
from tfm_rag.domain.value_objects.evaluation_report import (
    EvaluationReport,
    EvaluationSummary,
)


def _empty_report() -> EvaluationReport:
    when = datetime(2026, 6, 14, 0, 0, tzinfo=UTC)
    return EvaluationReport(
        chatbot_id=UUID("11111111-1111-1111-1111-111111111111"),
        chatbot_name="bot",
        dataset_path="eval/x.jsonl",
        scenario_filter=None,
        run_started_at=when,
        run_finished_at=datetime(2026, 6, 14, 0, 1, tzinfo=UTC),
        ragas_judge_model="llama3.1",
        cases=[],
        summary=EvaluationSummary(
            num_cases=0,
            num_scored=0,
            num_errors=0,
            num_skipped=0,
            metrics={},
            metrics_std={},
            per_scenario={},
        ),
    )


def test_write_report_canonical_names(tmp_path: Path) -> None:
    paths = write_report(_empty_report(), output_dir=tmp_path, timestamped=False)
    assert paths.json_path == tmp_path / "report.json"
    assert paths.markdown_path == tmp_path / "report.md"
    assert (tmp_path / "report.json").is_file()
    assert (tmp_path / "report.md").is_file()


def test_write_report_timestamped_default(tmp_path: Path) -> None:
    paths = write_report(_empty_report(), output_dir=tmp_path)
    assert paths.json_path.name.startswith("report_")
    assert paths.json_path.name.endswith(".json")
