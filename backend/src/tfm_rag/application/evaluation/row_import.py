import json
from typing import Any

from tfm_rag.domain.errors.evaluation import EvalDatasetError

_FIELDS = (
    "question", "ground_truth", "scenario", "complexity",
    "reference_contexts", "sql_reference", "source_doc",
)


def parse_jsonl_rows(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvalDatasetError(f"line {lineno}: invalid JSON ({exc})") from exc
        if not isinstance(obj, dict):
            raise EvalDatasetError(f"line {lineno}: expected a JSON object")
        out = {k: obj[k] for k in _FIELDS if k in obj}
        # Legacy datasets carry the source filename under metadata.source.
        if "source_doc" not in out:
            meta = obj.get("metadata")
            if isinstance(meta, dict) and meta.get("source"):
                out["source_doc"] = str(meta["source"])
        rows.append(out)
    return rows
