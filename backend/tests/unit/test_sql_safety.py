"""Unit tests for sql_safety.assert_select_only + enforce_limit."""
import pytest

from tfm_rag.application.chat.sql_safety import (
    assert_select_only,
    enforce_limit,
)
from tfm_rag.domain.errors.chat import UnsafeSQLError


# --- assert_select_only ------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "SELECT id, name FROM users",
        "  select * from users where id = 1  ",
        "SELECT id\nFROM users\nWHERE id = 1",
        # WITH/CTE leading SELECT is allowed
        "WITH t AS (SELECT 1) SELECT * FROM t",
        # Lowercase
        "select * from users",
    ],
)
def test_assert_select_only_accepts_safe_selects(sql: str) -> None:
    # should not raise
    assert_select_only(sql)


@pytest.mark.parametrize(
    "sql",
    [
        # Non-SELECT verbs
        "INSERT INTO users VALUES (1)",
        "UPDATE users SET name='x'",
        "DELETE FROM users",
        "DROP TABLE users",
        "ALTER TABLE users ADD COLUMN x INT",
        "TRUNCATE users",
        "CREATE TABLE x (id INT)",
        "GRANT ALL ON users TO ro",
        # Empty / whitespace
        "",
        "   ",
        # Multi-statement
        "SELECT 1; SELECT 2",
        "SELECT 1; DROP TABLE users",
        # Inline DML disguised after SELECT
        "SELECT 1 UNION SELECT id FROM users; DELETE FROM users",
    ],
)
def test_assert_select_only_rejects_unsafe(sql: str) -> None:
    with pytest.raises(UnsafeSQLError):
        assert_select_only(sql)


def test_assert_select_only_message_does_not_echo_full_sql() -> None:
    # Defensive: an error message must not echo the entire SQL (could be huge),
    # but it MAY include a short tag of the offending verb.
    try:
        assert_select_only("DELETE FROM secret_table WHERE x = 1")
    except UnsafeSQLError as exc:
        msg = str(exc)
        assert "DELETE" in msg.upper()


# --- enforce_limit -----------------------------------------------------------


def test_enforce_limit_appends_when_missing() -> None:
    out = enforce_limit("SELECT * FROM users", row_limit=50)
    assert out.lower().endswith("limit 51")


def test_enforce_limit_replaces_when_above_cap() -> None:
    out = enforce_limit("SELECT * FROM users LIMIT 9999", row_limit=50)
    assert "LIMIT 51" in out.upper()
    assert "9999" not in out


def test_enforce_limit_keeps_user_limit_when_below_cap() -> None:
    out = enforce_limit("SELECT * FROM users LIMIT 10", row_limit=50)
    # Below-cap user limit is preserved; we DO NOT raise it.
    assert "LIMIT 10" in out.upper()


def test_enforce_limit_is_case_insensitive() -> None:
    out = enforce_limit("select * from users limit 5", row_limit=50)
    assert "limit 5" in out.lower()


def test_enforce_limit_handles_trailing_semicolon() -> None:
    out = enforce_limit("SELECT * FROM users;", row_limit=50)
    # Should still produce a single, semicolon-free SELECT with LIMIT 51.
    assert out.count(";") == 0
    assert "LIMIT 51" in out.upper()


def test_enforce_limit_zero_or_negative_clamped_to_one() -> None:
    out = enforce_limit("SELECT * FROM users", row_limit=0)
    assert "LIMIT 2" in out.upper()  # row_limit=0 → request LIMIT 1+1 = 2 → keep 1 row
