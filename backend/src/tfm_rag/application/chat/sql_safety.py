"""SQL-safety helpers for the query_database tool.

* `assert_select_only(sql)` — rejects anything that isn't a single
  read-only SELECT statement.
* `enforce_limit(sql, row_limit)` — appends or rewrites the trailing
  LIMIT clause so the connector requests `row_limit + 1` rows (the +1
  lets the connector detect truncation).

Both helpers are deliberately small and regex-based — we do NOT pull in
sqlparse. The connector still enforces a hard timeout + server-side
behavior as a defence-in-depth layer.
"""
import re

from tfm_rag.domain.errors.chat import UnsafeSQLError

# Verbs that, if they appear as the leading non-whitespace token, mean
# the statement mutates state. We reject any non-SELECT.
_LEADING_VERB_RE = re.compile(
    r"^\s*(WITH|SELECT)\b",
    re.IGNORECASE,
)

# Banned tokens that, if present ANYWHERE in the SQL, indicate a
# multi-statement or DML attempt. Whole-word boundaries reduce false
# positives (e.g. "deleted_at" as a column name is fine).
_BANNED_TOKEN_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|"
    r"REPLACE|MERGE|CALL|EXEC|EXECUTE|VACUUM|ANALYZE)\b",
    re.IGNORECASE,
)


def assert_select_only(sql: str) -> None:
    """Raise UnsafeSQLError unless `sql` is a single read-only SELECT.

    Rules:
      * Leading non-whitespace token must be SELECT or WITH.
      * Must not contain banned mutating verbs as standalone tokens.
      * Must not contain ';' followed by additional non-whitespace
        characters (i.e. no second statement).
    """
    if not sql or not sql.strip():
        raise UnsafeSQLError("empty SQL is not allowed")

    if _LEADING_VERB_RE.match(sql) is None:
        first = sql.strip().split(None, 1)[0].upper()
        raise UnsafeSQLError(
            f"only SELECT (or WITH … SELECT) statements are allowed; got {first}"
        )

    match = _BANNED_TOKEN_RE.search(sql)
    if match is not None:
        raise UnsafeSQLError(
            f"banned SQL token detected: {match.group(0).upper()}"
        )

    # Reject "; <anything non-whitespace>" — multi-statement guard.
    # We allow a single trailing ';'.
    stripped = sql.rstrip().rstrip(";")
    if ";" in stripped:
        raise UnsafeSQLError("multi-statement SQL is not allowed")


_TRAILING_LIMIT_RE = re.compile(
    r"\blimit\s+(\d+)\b\s*;?\s*$",
    re.IGNORECASE,
)


def enforce_limit(sql: str, row_limit: int) -> str:
    """Return `sql` rewritten so it carries `LIMIT N`.

    We ask the database for `row_limit + 1` rows. The connector trims to
    `row_limit` and sets `SqlQueryResult.truncated=True` if it had to.

    * If the SQL already has `LIMIT k` and `k <= row_limit`, it's kept.
    * If `k > row_limit`, we replace it.
    * If there's no LIMIT, we append one.
    * Trailing `;` is stripped (we want a single statement, no semicolon).
    """
    effective = max(int(row_limit), 1) + 1
    sql = sql.rstrip().rstrip(";").rstrip()
    m = _TRAILING_LIMIT_RE.search(sql)
    if m is not None:
        existing = int(m.group(1))
        if existing <= row_limit:
            return sql  # user already self-limited below cap
        return _TRAILING_LIMIT_RE.sub(f"LIMIT {effective}", sql)
    return f"{sql} LIMIT {effective}"
