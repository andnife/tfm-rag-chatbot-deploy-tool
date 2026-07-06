import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "validate-dataset.py"


def _write_jsonl(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "dataset.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    return path


def _valid_row() -> dict:
    return {
        "question": "What does the product do?",
        "ground_truth": "It deploys RAG chatbots.",
        "reference_contexts": ["The product deploys RAG chatbots."],
        "scenario": "doc_only",
        "complexity": "factual",
        "metadata": {"source": "producto.txt", "loader": "txt"},
    }


def test_validator_accepts_valid_dataset(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path, [_valid_row()])
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_validator_rejects_missing_required_field(tmp_path: Path) -> None:
    bad = _valid_row()
    del bad["ground_truth"]
    path = _write_jsonl(tmp_path, [bad])
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "ground_truth" in result.stderr


def test_validator_requires_sql_reference_for_sql_only(tmp_path: Path) -> None:
    bad = _valid_row()
    bad["scenario"] = "sql_only"
    path = _write_jsonl(tmp_path, [bad])
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "sql_reference" in result.stderr
