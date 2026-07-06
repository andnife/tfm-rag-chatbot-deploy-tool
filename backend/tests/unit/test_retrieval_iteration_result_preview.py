from tfm_rag.domain.value_objects.retrieval_iteration import RetrievalIteration


def test_result_preview_roundtrips() -> None:
    it = RetrievalIteration(
        index=0, tool="query_database", query=None, num_chunks=None,
        latency_ms=12.0, sql="SELECT 1", row_count=1,
        result_preview="| n |\n|---|\n| 1 |",
    )
    d = it.to_dict()
    assert d["result_preview"] == "| n |\n|---|\n| 1 |"
    back = RetrievalIteration.from_dict(d)
    assert back.result_preview == "| n |\n|---|\n| 1 |"


def test_result_preview_defaults_none_and_tolerates_missing_key() -> None:
    it = RetrievalIteration(
        index=0, tool="docs", query="q", num_chunks=3, latency_ms=1.0,
    )
    assert it.result_preview is None
    assert it.to_dict()["result_preview"] is None
    # Legacy dict without the key must still parse.
    legacy = {
        "index": 0, "tool": "docs", "query": "q", "num_chunks": 3,
        "latency_ms": 1.0, "sql": None, "row_count": None,
    }
    assert RetrievalIteration.from_dict(legacy).result_preview is None
