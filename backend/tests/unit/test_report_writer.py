import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from tfm_rag.application.evaluation.report_writer import write_report
from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase
from tfm_rag.domain.value_objects.evaluation_report import (
    EvaluationReport,
    EvaluationSummary,
)


def _report(cases: list[EvaluationCase]) -> EvaluationReport:
    when = datetime(2026, 5, 24, 10, 0, tzinfo=UTC)
    return EvaluationReport(
        chatbot_id=uuid4(),
        chatbot_name="HistoryBot",
        dataset_path="/tmp/ds.jsonl",
        scenario_filter="doc_only",
        run_started_at=when,
        run_finished_at=when,
        ragas_judge_model="llama3.1",
        cases=cases,
        summary=EvaluationSummary.from_cases(cases),
    )


def _scored(q: str, f: float, ar: float, cp: float, cr: float) -> EvaluationCase:
    return EvaluationCase(
        question=q, ground_truth="gt", scenario="doc_only", metadata={},
        predicted_answer="a", retrieved_contexts=["c"],
        scores={
            "faithfulness": f,
            "answer_relevancy": ar,
            "context_precision": cp,
            "context_recall": cr,
        },
    )


def test_write_report_emits_report_json_and_md(tmp_path: Path) -> None:
    cases = [_scored("Q1?", 0.8, 0.9, 0.8, 0.7), _scored("Q2?", 0.5, 0.6, 0.5, 0.4)]
    report = _report(cases)

    paths = write_report(report, output_dir=tmp_path)

    assert paths.json_path.exists()
    assert paths.markdown_path.exists()
    assert paths.json_path.name == "report.json"
    assert paths.markdown_path.name == "report.md"

    data = json.loads(paths.json_path.read_text(encoding="utf-8"))
    assert data["chatbot_name"] == "HistoryBot"
    assert data["summary"]["num_cases"] == 2
    assert len(data["cases"]) == 2


def test_markdown_report_contains_summary_table(tmp_path: Path) -> None:
    cases = [_scored("Q?", 0.7, 0.8, 0.6, 0.5)]
    report = _report(cases)
    paths = write_report(report, output_dir=tmp_path)

    md = paths.markdown_path.read_text(encoding="utf-8")
    assert "# Evaluation report" in md
    assert "| Metric | Score |" in md
    assert "faithfulness" in md
    assert "answer_relevancy" in md


def test_markdown_report_includes_top_failures(tmp_path: Path) -> None:
    cases = [
        _scored("Q1?", 0.9, 0.9, 0.8, 0.7),
        _scored("Q2?", 0.2, 0.4, 0.3, 0.2),
        _scored("Q3?", 0.5, 0.6, 0.5, 0.4),
    ]
    report = _report(cases)
    paths = write_report(report, output_dir=tmp_path)

    md = paths.markdown_path.read_text(encoding="utf-8")
    assert "## Top failures by faithfulness" in md
    assert "Q2?" in md


def test_write_report_creates_output_dir_if_missing(tmp_path: Path) -> None:
    deep_dir = tmp_path / "a" / "b" / "c"
    assert not deep_dir.exists()
    cases = [_scored("Q?", 0.5, 0.5, 0.5, 0.5)]
    report = _report(cases)
    paths = write_report(report, output_dir=deep_dir)
    assert deep_dir.exists()
    assert paths.json_path.exists()
