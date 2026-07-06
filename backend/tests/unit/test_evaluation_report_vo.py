from datetime import UTC, datetime
from uuid import uuid4

from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase
from tfm_rag.domain.value_objects.evaluation_report import (
    EvaluationReport,
    EvaluationSummary,
)


def _case(
    score_f: float = 0.7,
    score_ar: float = 0.8,
    *,
    scenario: str = "doc_only",
) -> EvaluationCase:
    return EvaluationCase(
        question="q",
        ground_truth="gt",
        scenario=scenario,
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


def test_summary_reports_std_per_metric() -> None:
    cases = [_case(0.6, 0.8), _case(0.8, 0.8), _case(1.0, 0.8)]
    summary = EvaluationSummary.from_cases(cases)
    # faithfulness = [0.6, 0.8, 1.0] → sample stdev = 0.2
    assert abs(summary.metrics_std["faithfulness"] - 0.2) < 1e-6
    # answer_relevancy is constant → stdev 0.0
    assert summary.metrics_std["answer_relevancy"] == 0.0


def test_summary_counts_skipped_cases() -> None:
    """A case with no error and no scores (e.g. empty contexts, not abstain)
    is 'skipped', distinct from 'errored'. Reported separately so a low
    num_scored isn't mistaken for failures."""
    scored = _case(0.7, 0.8)
    skipped = EvaluationCase(
        question="q", ground_truth="gt", scenario="doc_only", metadata={},
        predicted_answer="a", retrieved_contexts=[], scores=None,
    )
    err = EvaluationCase(
        question="q", ground_truth="gt", scenario="doc_only", metadata={},
        error="boom",
    )
    summary = EvaluationSummary.from_cases([scored, skipped, err])
    assert summary.num_cases == 3
    assert summary.num_scored == 1
    assert summary.num_errors == 1
    assert summary.num_skipped == 1


def test_summary_breaks_down_by_scenario() -> None:
    doc = _case(0.6, 0.8, scenario="doc_only")
    doc2 = _case(0.8, 0.8, scenario="doc_only")
    sql = _case(0.4, 0.5, scenario="sql_only")
    summary = EvaluationSummary.from_cases([doc, doc2, sql])

    assert set(summary.per_scenario.keys()) == {"doc_only", "sql_only"}
    assert summary.per_scenario["doc_only"]["num_scored"] == 2
    assert abs(summary.per_scenario["doc_only"]["metrics"]["faithfulness"] - 0.7) < 1e-6
    assert summary.per_scenario["sql_only"]["num_scored"] == 1
    assert summary.per_scenario["sql_only"]["metrics"]["faithfulness"] == 0.4


def test_summary_to_dict_includes_new_fields() -> None:
    summary = EvaluationSummary.from_cases([_case(0.7, 0.8)])
    data = summary.to_dict()
    assert "metrics_std" in data
    assert "num_skipped" in data
    assert "per_scenario" in data


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
        generator_model="llama-3.3-70b",
        cases=cases,
        summary=EvaluationSummary.from_cases(cases),
    )
    data = report.to_dict()
    assert data["chatbot_id"] == str(chatbot_id)
    assert data["chatbot_name"] == "HistoryBot"
    assert data["dataset_path"] == "/tmp/ds.jsonl"
    assert data["scenario_filter"] == "doc_only"
    assert data["ragas_judge_model"] == "llama3.1"
    assert data["generator_model"] == "llama-3.3-70b"
    assert data["run_started_at"] == when.isoformat()
    assert isinstance(data["cases"], list)
    assert len(data["cases"]) == 1
    assert data["summary"]["num_cases"] == 1


def _case_with_tokens(
    prompt_tokens: int,
    completion_tokens: int,
    score_f: float = 0.7,
    scenario: str = "doc_only",
) -> EvaluationCase:
    c = EvaluationCase(
        question="q", ground_truth="gt", scenario=scenario,
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        predicted_answer="a", retrieved_contexts=["x"],
        scores={"faithfulness": score_f},
    )
    return c


def test_summary_sums_token_totals() -> None:
    cases = [
        _case_with_tokens(prompt_tokens=10, completion_tokens=4),
        _case_with_tokens(prompt_tokens=20, completion_tokens=8),
    ]
    summary = EvaluationSummary.from_cases(cases)
    data = summary.to_dict()
    assert "tokens" in data
    assert data["tokens"]["gen_prompt"] == 30
    assert data["tokens"]["gen_completion"] == 12


def test_summary_token_totals_zero_by_default() -> None:
    cases = [_case()]
    summary = EvaluationSummary.from_cases(cases)
    data = summary.to_dict()
    assert data["tokens"]["gen_prompt"] == 0
    assert data["tokens"]["gen_completion"] == 0


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
