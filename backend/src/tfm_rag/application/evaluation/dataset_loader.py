import json
from pathlib import Path
from typing import Any

from tfm_rag.domain.errors.evaluation import EvaluationDatasetError
from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase

_REQUIRED_FIELDS = ("question", "ground_truth", "scenario")


def _parse_line(line_no: int, raw: str) -> dict[str, Any]:
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EvaluationDatasetError(
            f"Malformed JSON on line {line_no}: {exc.msg}"
        ) from exc
    if not isinstance(obj, dict):
        raise EvaluationDatasetError(
            f"Line {line_no}: expected a JSON object, got {type(obj).__name__}"
        )
    for field in _REQUIRED_FIELDS:
        if field not in obj:
            raise EvaluationDatasetError(
                f"Line {line_no}: missing required field {field!r}"
            )
    return obj


def load_evaluation_dataset(
    path: Path,
    *,
    scenario_filter: str | None = None,
) -> list[EvaluationCase]:
    """Read a JSONL evaluation dataset.

    Each non-blank line must be a JSON object with at least
    ``question``, ``ground_truth``, ``scenario``. ``metadata`` is
    optional (defaults to ``{}``).

    ``scenario_filter``: if set, only entries with matching ``scenario``
    are kept.

    Raises ``EvaluationDatasetError`` for missing files, malformed JSON
    (with line number), or entries missing required fields.
    """
    path = Path(path)
    if not path.exists():
        raise EvaluationDatasetError(f"Dataset file does not exist: {path}")

    cases: list[EvaluationCase] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            if not raw.strip():
                continue
            obj = _parse_line(line_no, raw)
            case = EvaluationCase(
                question=str(obj["question"]),
                ground_truth=str(obj["ground_truth"]),
                scenario=str(obj["scenario"]),
                metadata=dict(obj.get("metadata") or {}),
            )
            if scenario_filter and case.scenario != scenario_filter:
                continue
            cases.append(case)
    return cases
