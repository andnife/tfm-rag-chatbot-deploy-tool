from datetime import UTC, datetime
from uuid import uuid4

from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase
from tfm_rag.domain.value_objects.evaluation_report import (
    EvaluationReport,
    EvaluationSummary,
)


def _case(score_f: float = 0.7, score_ar: float = 0.8) -> EvaluationCase:
    return EvaluationCase(
        question="q",
        ground_truth="gt",
        scenario="doc_only",
        metadata={},
        predicted_answer="a",
        retrieved_contexts=["x"],
        scores={"faithfulness": score_f, "answer_relevancy": score_ar},
    )


def test_summary_averages_per_metric_skipping_errors() -> None:
    cases = [_case(0.6, 0.8), _case(0.8, 0.9), _case(0.5, 0.5)]
    err = EvaluationCase(
        question="q4", ground_truth="gt", scenario="doc_only", metadata={},
        error="LLM timeout", scores=None,
    )
    cases.append(err)

    summary = EvaluationSummary.from_cases(cases)
    assert summary.num_cases == 4
    assert summary.num_errors == 1
    assert summary.num_scored == 3
    assert abs(summary.metrics["faithfulness"] - 0.6333333) < 1e-4
    assert abs(summary.metrics["answer_relevancy"] - 0.7333333) < 1e-4


def test_summary_with_no_scored_cases_yields_empty_metrics() -> None:
    err = EvaluationCase(
        question="q", ground_truth="gt", scenario="doc_only", metadata={},
        error="boom",
    )
    summary = EvaluationSummary.from_cases([err])
    assert summary.num_cases == 1
    assert summary.num_errors == 1
    assert summary.num_scored == 0
    assert summary.metrics == {}


def test_report_to_dict_contains_config_and_cases() -> None:
    chatbot_id = uuid4()
    when = datetime(2026, 5, 24, 10, 0, tzinfo=UTC)
    cases = [_case()]
    report = EvaluationReport(
        chatbot_id=chatbot_id,
        chatbot_name="HistoryBot",
        dataset_path="/tmp/ds.jsonl",
        scenario_filter="doc_only",
        run_started_at=when,
        run_finished_at=when,
        ragas_judge_model="llama3.1",
        cases=cases,
        summary=EvaluationSummary.from_cases(cases),
    )
    data = report.to_dict()
    assert data["chatbot_id"] == str(chatbot_id)
    assert data["chatbot_name"] == "HistoryBot"
    assert data["dataset_path"] == "/tmp/ds.jsonl"
    assert data["scenario_filter"] == "doc_only"
    assert data["ragas_judge_model"] == "llama3.1"
    assert data["run_started_at"] == when.isoformat()
    assert isinstance(data["cases"], list)
    assert len(data["cases"]) == 1
    assert data["summary"]["num_cases"] == 1


def test_report_top_failures_returns_worst_cases_per_metric() -> None:
    good = _case(0.9, 0.9)
    bad = _case(0.1, 0.95)
    worse = _case(0.05, 0.5)
    report = EvaluationReport(
        chatbot_id=uuid4(),
        chatbot_name="X",
        dataset_path="/tmp/ds.jsonl",
        scenario_filter=None,
        run_started_at=datetime.now(UTC),
        run_finished_at=datetime.now(UTC),
        ragas_judge_model="llama3.1",
        cases=[good, bad, worse],
        summary=EvaluationSummary.from_cases([good, bad, worse]),
    )
    top = report.top_failures(metric="faithfulness", n=2)
    assert len(top) == 2
    assert top[0].scores["faithfulness"] == 0.05
    assert top[1].scores["faithfulness"] == 0.1
