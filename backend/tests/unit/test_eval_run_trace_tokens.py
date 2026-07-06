"""
Unit tests for TraceRowOut token/ETA optional fields.

These fields are written by `_on_case_with_tokens` (eval_datasets.py) but absent
on older file-run trace rows.  The test exercises the pure model parsing — no DB
or network needed.
"""

import json
from pathlib import Path

import pytest

from tfm_rag.infrastructure.api.routers.eval_runs import TraceRowOut

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_row(**extra) -> dict:  # noqa: ANN003
    return {
        "idx": 0,
        "total": 5,
        "question": "What is X?",
        "scenario": None,
        "ground_truth": "X is Y.",
        "predicted_answer": "X is Y.",
        "iterations": [],
        "citations": [],
        "retrieved_contexts": [],
        "judged_correct": True,
        "judge_reason": "correct",
        "error": None,
        **extra,
    }


# ---------------------------------------------------------------------------
# New fields round-trip through TraceRowOut
# ---------------------------------------------------------------------------

def test_trace_row_carries_token_fields() -> None:
    """A row with all 5 new fields is parsed correctly."""
    row = TraceRowOut(
        **_base_row(
            prompt_tokens=120,
            completion_tokens=55,
            cumulative_prompt_tokens=240,
            cumulative_completion_tokens=110,
            eta_seconds=14.3,
        )
    )
    assert row.prompt_tokens == 120
    assert row.completion_tokens == 55
    assert row.cumulative_prompt_tokens == 240
    assert row.cumulative_completion_tokens == 110
    assert row.eta_seconds == pytest.approx(14.3)


def test_trace_row_token_fields_default_to_none() -> None:
    """A legacy row without the new fields yields None for all 5."""
    row = TraceRowOut(**_base_row())
    assert row.prompt_tokens is None
    assert row.completion_tokens is None
    assert row.cumulative_prompt_tokens is None
    assert row.cumulative_completion_tokens is None
    assert row.eta_seconds is None


# ---------------------------------------------------------------------------
# Simulate the trace reader (json.loads → TraceRowOut(**...))
# ---------------------------------------------------------------------------

def test_trace_reader_new_row(tmp_path: Path) -> None:
    """Mimics the trace-file reader for a row that contains the 5 new fields."""
    record = _base_row(
        prompt_tokens=80,
        completion_tokens=30,
        cumulative_prompt_tokens=80,
        cumulative_completion_tokens=30,
        eta_seconds=9.5,
    )
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    rows: list[TraceRowOut] = []
    with trace_path.open(encoding="utf-8") as fh:
        for raw in fh:
            if not raw.strip():
                continue
            try:
                rows.append(TraceRowOut(**json.loads(raw)))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

    assert len(rows) == 1
    r = rows[0]
    assert r.prompt_tokens == 80
    assert r.eta_seconds == pytest.approx(9.5)


def test_trace_reader_legacy_row(tmp_path: Path) -> None:
    """Legacy rows (no token fields) parse without error; new fields are None."""
    record = _base_row()
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    rows: list[TraceRowOut] = []
    with trace_path.open(encoding="utf-8") as fh:
        for raw in fh:
            if not raw.strip():
                continue
            try:
                rows.append(TraceRowOut(**json.loads(raw)))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

    assert len(rows) == 1
    assert rows[0].prompt_tokens is None
    assert rows[0].completion_tokens is None
