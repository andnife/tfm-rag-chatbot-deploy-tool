from tfm_rag.domain.value_objects.grade_verdict import GradeVerdict


def test_sufficient_round_trip() -> None:
    v = GradeVerdict(sufficient=True)
    d = v.to_dict()
    assert d == {
        "sufficient": True,
        "reformulated_query": None,
        "fixed_sql": None,
        "abstain_reason": None,
    }
    assert GradeVerdict.from_dict(d) == v


def test_insufficient_with_reformulation_round_trip() -> None:
    v = GradeVerdict(sufficient=False, reformulated_query="rephrased question")
    assert GradeVerdict.from_dict(v.to_dict()) == v


def test_insufficient_with_fixed_sql_and_abstain() -> None:
    v = GradeVerdict(
        sufficient=False, fixed_sql="SELECT 1", abstain_reason="not enough data"
    )
    assert GradeVerdict.from_dict(v.to_dict()) == v


def test_from_dict_tolerates_missing_optionals() -> None:
    v = GradeVerdict.from_dict({"sufficient": False})
    assert v.sufficient is False
    assert v.reformulated_query is None
    assert v.fixed_sql is None
    assert v.abstain_reason is None
