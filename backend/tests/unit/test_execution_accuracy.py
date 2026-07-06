from tfm_rag.application.evaluation.execution_accuracy import (
    execution_accuracy,
    rows_match,
)


def test_identical_rows_match_regardless_of_order() -> None:
    a = [{"x": 1}, {"x": 2}]
    b = [{"x": 2}, {"x": 1}]
    assert rows_match(a, b) is True
    assert execution_accuracy(a, b) == 1.0


def test_different_rows_do_not_match() -> None:
    assert rows_match([{"x": 1}], [{"x": 2}]) is False
    assert execution_accuracy([{"x": 1}], [{"x": 2}]) == 0.0


def test_numeric_string_normalisation() -> None:
    # "5" and 5 and 5.0 should be treated equal.
    assert rows_match([{"n": "5"}], [{"n": 5}]) is True
    assert rows_match([{"n": 5.0}], [{"n": 5}]) is True


def test_empty_vs_nonempty() -> None:
    assert execution_accuracy([], [{"x": 1}]) == 0.0
    assert execution_accuracy([], []) == 1.0


def test_boolean_cell_value_distinct_from_int() -> None:
    # MySQL TINYINT(1) returns Python bool; True must not equal int 1.
    assert rows_match([{"active": True}], [{"active": True}]) is True
    assert rows_match([{"active": True}], [{"active": 1}]) is False


def test_text_column_string_values() -> None:
    assert rows_match([{"name": "alice"}], [{"name": "alice"}]) is True
    assert rows_match([{"name": "alice"}], [{"name": "bob"}]) is False


def test_single_column_alias_mismatch_still_matches_by_value() -> None:
    # COUNT(id) vs COUNT(*): different alias, same aggregate value.
    a = [{"COUNT(id)": 40}]
    b = [{"COUNT(*)": 40}]
    assert rows_match(a, b) is True
    assert execution_accuracy(a, b) == 1.0


def test_single_column_alias_mismatch_different_values_do_not_match() -> None:
    a = [{"name": "India"}]
    b = [{"country": "Estados Unidos"}]
    assert rows_match(a, b) is False
    assert execution_accuracy(a, b) == 0.0


def test_multi_column_rows_still_compared_strictly() -> None:
    # Value-swap across columns must NOT match: multi-col path stays column-aware.
    a = [{"a": 1, "b": 2}]
    b = [{"a": 2, "b": 1}]
    assert rows_match(a, b) is False


def test_single_column_multiset_order_insensitive() -> None:
    a = [{"COUNT(id)": 1}, {"COUNT(id)": 2}]
    b = [{"total": 2}, {"total": 1}]
    assert rows_match(a, b) is True


def test_extra_columns_on_single_col_reference_still_match() -> None:
    # Gold `SELECT name` → 'España'; prediction `SELECT name, gdp` → same answer
    # plus an extra column. Counts as correct (the answer is contained).
    gold = [{"name": "España"}]
    pred = [{"name": "España", "gdp_usd_bn": 1580.7}]
    assert rows_match(pred, gold) is True
    assert execution_accuracy(pred, gold) == 1.0


def test_extra_columns_but_wrong_answer_does_not_match() -> None:
    gold = [{"name": "España"}]
    pred = [{"name": "Francia", "gdp_usd_bn": 2923.5}]
    assert rows_match(pred, gold) is False


def test_extra_rows_do_not_match_single_col_reference() -> None:
    # Prediction returns MORE rows than the reference → different answer.
    gold = [{"name": "España"}]
    pred = [{"name": "España", "x": 1}, {"name": "Francia", "x": 2}]
    assert rows_match(pred, gold) is False


def test_multi_row_names_with_extra_column_match() -> None:
    gold = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
    pred = [{"name": "B", "pop": 2}, {"name": "C", "pop": 3}, {"name": "A", "pop": 1}]
    assert rows_match(pred, gold) is True
