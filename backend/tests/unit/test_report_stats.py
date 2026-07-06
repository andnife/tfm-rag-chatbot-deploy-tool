import math

from tfm_rag.application.evaluation.report_stats import bootstrap_ci, summarize_report


def test_bootstrap_ci_constant_values() -> None:
    mean, lo, hi = bootstrap_ci([0.5, 0.5, 0.5, 0.5])
    assert mean == 0.5 and lo == 0.5 and hi == 0.5


def test_bootstrap_ci_single_value() -> None:
    assert bootstrap_ci([0.8]) == (0.8, 0.8, 0.8)


def test_bootstrap_ci_empty_is_nan() -> None:
    mean, lo, hi = bootstrap_ci([])
    assert math.isnan(mean) and math.isnan(lo) and math.isnan(hi)


def test_bootstrap_ci_deterministic_for_seed() -> None:
    vals = [0.1, 0.4, 0.6, 0.9, 0.3, 0.7, 0.5]
    assert bootstrap_ci(vals, seed=7) == bootstrap_ci(vals, seed=7)


def test_bootstrap_ci_brackets_mean() -> None:
    vals = [0.1, 0.4, 0.6, 0.9, 0.3, 0.7, 0.5, 0.2, 0.8]
    mean, lo, hi = bootstrap_ci(vals, seed=1)
    assert lo <= mean <= hi
    assert 0.0 <= lo <= 1.0 and 0.0 <= hi <= 1.0


def test_bootstrap_ci_skips_nan() -> None:
    mean, lo, hi = bootstrap_ci([0.2, float("nan"), 0.8], seed=42)
    assert mean == 0.5  # NaN dropped → mean of 0.2 and 0.8
    assert not math.isnan(lo) and not math.isnan(hi)
    assert lo <= mean <= hi


def _report() -> dict:
    return {
        "cases": [
            {
                "scenario": "doc_only",
                "scores": {"faithfulness": 0.8, "answer_relevancy": 0.9},
                "total_latency_ms": 100.0,
            },
            {
                "scenario": "doc_only",
                "scores": {"faithfulness": 0.6, "answer_relevancy": 0.7},
                "total_latency_ms": 200.0,
            },
            {
                "scenario": "sql_only",
                "scores": {"faithfulness": 1.0, "answer_relevancy": 1.0},
                "total_latency_ms": 50.0,
            },
            {"scenario": "abstain", "scores": None, "total_latency_ms": 10.0},
        ]
    }


def test_summarize_report_metrics_and_latency() -> None:
    out = summarize_report(_report(), n_resamples=200, seed=3)
    # overall metrics present with mean/ci/n
    fm = out["metrics"]["faithfulness"]
    assert fm["n"] == 3
    assert fm["ci_lower"] <= fm["mean"] <= fm["ci_upper"]
    # overall latency mean over the 4 cases that have it
    assert out["latency"]["n"] == 4
    assert out["latency"]["mean_ms"] == (100.0 + 200.0 + 50.0 + 10.0) / 4
    # per-scenario breakdown
    assert "doc_only" in out["per_scenario"]
    assert out["per_scenario"]["doc_only"]["metrics"]["faithfulness"]["n"] == 2


def test_summarize_report_handles_empty_cases() -> None:
    out = summarize_report({"cases": []}, n_resamples=10)
    assert out["metrics"] == {}
    assert out["latency"]["n"] == 0
    assert math.isnan(out["latency"]["mean_ms"])
