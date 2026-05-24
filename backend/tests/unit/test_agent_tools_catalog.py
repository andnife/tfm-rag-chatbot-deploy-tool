import pytest

from tfm_rag.domain.catalog import agent_tools


def test_tool_name_constants_are_distinct() -> None:
    names = {
        agent_tools.TOOL_SEARCH_DOCS,
        agent_tools.TOOL_FINAL_ANSWER,
        agent_tools.TOOL_ABSTAIN,
        agent_tools.TOOL_QUERY_DATABASE,
    }
    assert len(names) == 4


def test_tool_name_constants_have_expected_values() -> None:
    assert agent_tools.TOOL_SEARCH_DOCS == "search_docs"
    assert agent_tools.TOOL_FINAL_ANSWER == "final_answer"
    assert agent_tools.TOOL_ABSTAIN == "abstain"
    assert agent_tools.TOOL_QUERY_DATABASE == "query_database"


def test_build_tool_schemas_default_excludes_query_database() -> None:
    schemas = agent_tools.build_tool_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert agent_tools.TOOL_SEARCH_DOCS in names
    assert agent_tools.TOOL_FINAL_ANSWER in names
    assert agent_tools.TOOL_ABSTAIN in names
    assert agent_tools.TOOL_QUERY_DATABASE not in names


def test_build_tool_schemas_can_include_query_database() -> None:
    schemas = agent_tools.build_tool_schemas(include_query_database=True)
    names = {s["function"]["name"] for s in schemas}
    assert agent_tools.TOOL_QUERY_DATABASE in names


def test_each_tool_schema_has_required_keys() -> None:
    for schema in agent_tools.build_tool_schemas(include_query_database=True):
        assert schema["type"] == "function"
        fn = schema["function"]
        assert isinstance(fn["name"], str)
        assert isinstance(fn["description"], str)
        params = fn["parameters"]
        assert params["type"] == "object"
        assert "properties" in params


def test_search_docs_requires_query_argument() -> None:
    schemas = {s["function"]["name"]: s for s in agent_tools.build_tool_schemas()}
    s = schemas[agent_tools.TOOL_SEARCH_DOCS]
    assert "query" in s["function"]["parameters"]["properties"]
    assert "query" in s["function"]["parameters"]["required"]


def test_final_answer_requires_answer_argument() -> None:
    schemas = {s["function"]["name"]: s for s in agent_tools.build_tool_schemas()}
    s = schemas[agent_tools.TOOL_FINAL_ANSWER]
    assert "answer" in s["function"]["parameters"]["properties"]
    assert "answer" in s["function"]["parameters"]["required"]
