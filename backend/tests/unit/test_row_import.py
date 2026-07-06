import pytest

from tfm_rag.application.evaluation.row_import import parse_jsonl_rows
from tfm_rag.domain.errors.evaluation import EvalDatasetError


def test_parse_jsonl_rows_maps_fields_and_legacy_source() -> None:
    text = (
        '{"question": "¿garantía?", "ground_truth": "3 años", '
        '"scenario": "doc_only", "complexity": "factual", '
        '"reference_contexts": ["..."], "metadata": {"source": "manual.md"}}\n'
        '\n'
        '{"question": "¿pedidos?", "ground_truth": "5", "scenario": "sql_only", '
        '"complexity": "factual", "sql_reference": "SELECT count(*) FROM orders"}\n'
    )
    rows = parse_jsonl_rows(text)
    assert len(rows) == 2
    assert rows[0]["source_doc"] == "manual.md"
    assert rows[0]["reference_contexts"] == ["..."]
    assert rows[1]["sql_reference"].startswith("SELECT")


def test_parse_jsonl_rows_rejects_malformed_json() -> None:
    with pytest.raises(EvalDatasetError):
        parse_jsonl_rows("{not json}\n")
