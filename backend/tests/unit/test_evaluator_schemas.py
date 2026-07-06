from tfm_rag.domain.catalog.evaluator_schemas import (
    GRADE_VERDICT_TOOL,
    RUN_QUERY_TOOL,
    build_grade_verdict_schema,
    build_run_query_schema,
)


def test_grade_verdict_schema_shape() -> None:
    tools = build_grade_verdict_schema()
    assert [t["function"]["name"] for t in tools] == [GRADE_VERDICT_TOOL]
    props = tools[0]["function"]["parameters"]["properties"]
    assert set(props) == {
        "sufficient", "reformulated_query", "fixed_sql", "abstain_reason",
    }
    assert tools[0]["function"]["parameters"]["required"] == ["sufficient"]
    assert props["sufficient"]["type"] == "boolean"


def test_run_query_schema_shape() -> None:
    tools = build_run_query_schema()
    assert [t["function"]["name"] for t in tools] == [RUN_QUERY_TOOL]
    props = tools[0]["function"]["parameters"]["properties"]
    # No `purpose` field anymore — the model self-terminates by replying with
    # plain text instead of choosing explore/answer per call.
    assert set(props) == {"source_id", "sql"}
    assert tools[0]["function"]["parameters"]["required"] == ["source_id", "sql"]
