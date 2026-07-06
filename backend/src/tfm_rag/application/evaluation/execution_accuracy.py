"""Deterministic SQL execution-accuracy comparison for the SQL scenarios.

Compares the pipeline's SQL result with the dataset's reference result.

- **Single-column reference** (the common case: a name, a COUNT, an aggregate):
  the reference value(s) must be *contained* in the predicted rows — same row
  count, and each reference row's value matches a distinct predicted row by
  value, ignoring column name/alias and any EXTRA columns the prediction carries.
  So gold ``SELECT name`` → 'España' is satisfied by ``SELECT name, gdp`` →
  ('España', 1580.7): the model got the answer, it was just more verbose.
- **Multi-column reference**: strict column-aware multiset comparison, so a
  value-swap across columns is NOT a false match.

Order-insensitive; numeric/numeric-string values are normalised (5, 5.0, "5"
compare equal).
"""
from __future__ import annotations

from collections import Counter
from typing import Any


def _norm(value: Any) -> str:
    if value is None:
        return "\x00"
    if isinstance(value, bool):
        return str(value)
    try:
        f = float(value)
        return f"{f:.6g}"
    except (TypeError, ValueError):
        return str(value).strip().lower()


def _row_key(row: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """Column-aware key: (column, value) pairs. Used for multi-column refs."""
    return tuple(sorted((str(k).lower(), _norm(v)) for k, v in row.items()))


def _row_values(row: dict[str, Any]) -> Counter[str]:
    """Multiset of a row's normalised values (column names ignored)."""
    return Counter(_norm(v) for v in row.values())


def _is_submultiset(small: Counter[str], big: Counter[str]) -> bool:
    return all(big.get(k, 0) >= c for k, c in small.items())


def rows_match(
    predicted: list[dict[str, Any]], reference: list[dict[str, Any]]
) -> bool:
    if len(predicted) != len(reference):
        return False

    # Single-column reference → containment: each reference value must appear in
    # a distinct predicted row (which may carry extra columns / a different
    # alias). One-to-one matching, order-insensitive.
    if all(len(r) == 1 for r in reference):
        gold = [_row_values(r) for r in reference]
        pred = [_row_values(r) for r in predicted]
        used = [False] * len(pred)

        def _match(i: int) -> bool:
            if i == len(gold):
                return True
            for j in range(len(pred)):
                if not used[j] and _is_submultiset(gold[i], pred[j]):
                    used[j] = True
                    if _match(i + 1):
                        return True
                    used[j] = False
            return False

        return _match(0)

    # Multi-column reference → strict, column-aware (value-swap safe).
    return Counter(_row_key(r) for r in predicted) == Counter(
        _row_key(r) for r in reference
    )


def execution_accuracy(
    predicted: list[dict[str, Any]], reference: list[dict[str, Any]]
) -> float:
    return 1.0 if rows_match(predicted, reference) else 0.0
