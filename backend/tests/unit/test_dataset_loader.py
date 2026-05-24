import json
from pathlib import Path

import pytest

from tfm_rag.application.evaluation.dataset_loader import (
    load_evaluation_dataset,
)
from tfm_rag.domain.errors.evaluation import EvaluationDatasetError


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )


def test_load_dataset_returns_evaluation_cases(tmp_path: Path) -> None:
    p = tmp_path / "ds.jsonl"
    _write_jsonl(p, [
        {
            "question": "Q1?",
            "ground_truth": "GT1",
            "scenario": "doc_only",
            "metadata": {"difficulty": "easy"},
        },
        {
            "question": "Q2?",
            "ground_truth": "GT2",
            "scenario": "abstain",
        },
    ])
    cases = load_evaluation_dataset(p)
    assert len(cases) == 2
    assert cases[0].question == "Q1?"
    assert cases[0].scenario == "doc_only"
    assert cases[0].metadata == {"difficulty": "easy"}
    assert cases[1].metadata == {}


def test_load_dataset_filters_by_scenario(tmp_path: Path) -> None:
    p = tmp_path / "ds.jsonl"
    _write_jsonl(p, [
        {"question": "Q1?", "ground_truth": "gt", "scenario": "doc_only"},
        {"question": "Q2?", "ground_truth": "gt", "scenario": "abstain"},
        {"question": "Q3?", "ground_truth": "gt", "scenario": "doc_only"},
    ])
    cases = load_evaluation_dataset(p, scenario_filter="doc_only")
    assert len(cases) == 2
    assert all(c.scenario == "doc_only" for c in cases)


def test_load_dataset_skips_blank_lines(tmp_path: Path) -> None:
    p = tmp_path / "ds.jsonl"
    p.write_text(
        '{"question":"Q?", "ground_truth":"gt", "scenario":"doc_only"}\n'
        "\n"
        "   \n"
        '{"question":"Q2?", "ground_truth":"gt", "scenario":"doc_only"}\n',
        encoding="utf-8",
    )
    cases = load_evaluation_dataset(p)
    assert len(cases) == 2


def test_load_dataset_file_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(EvaluationDatasetError, match="does not exist"):
        load_evaluation_dataset(tmp_path / "missing.jsonl")


def test_load_dataset_malformed_json_raises_with_line_number(
    tmp_path: Path,
) -> None:
    p = tmp_path / "ds.jsonl"
    p.write_text(
        '{"question":"ok", "ground_truth":"gt", "scenario":"doc_only"}\n'
        "{this is not json}\n",
        encoding="utf-8",
    )
    with pytest.raises(EvaluationDatasetError, match="line 2"):
        load_evaluation_dataset(p)


def test_load_dataset_missing_required_field_raises(tmp_path: Path) -> None:
    p = tmp_path / "ds.jsonl"
    p.write_text(
        '{"question":"missing gt", "scenario":"doc_only"}\n',
        encoding="utf-8",
    )
    with pytest.raises(EvaluationDatasetError, match="ground_truth"):
        load_evaluation_dataset(p)
