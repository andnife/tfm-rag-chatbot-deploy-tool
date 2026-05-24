from tfm_rag.domain.catalog import eval_scenarios


def test_scenario_constants_have_expected_values() -> None:
    assert eval_scenarios.SCENARIO_DOC_ONLY == "doc_only"
    assert eval_scenarios.SCENARIO_SQL_ONLY == "sql_only"
    assert eval_scenarios.SCENARIO_MIXED == "mixed"
    assert eval_scenarios.SCENARIO_ABSTAIN == "abstain"


def test_known_scenarios_includes_all_four() -> None:
    assert eval_scenarios.KNOWN_SCENARIOS == {
        "doc_only", "sql_only", "mixed", "abstain",
    }


def test_is_known_scenario_recognises_known_and_unknown() -> None:
    assert eval_scenarios.is_known_scenario("doc_only") is True
    assert eval_scenarios.is_known_scenario("mixed") is True
    assert eval_scenarios.is_known_scenario("free-form") is False
