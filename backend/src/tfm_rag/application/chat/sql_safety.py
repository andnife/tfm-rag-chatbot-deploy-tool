"""SQL-safety helpers for the query_database tool.

* `assert_read_only(sql)` — rejects anything that isn't a single read-only
  statement. Read-only means SELECT-family queries (SELECT/UNION/WITH) plus
  metadata introspection (SHOW/DESCRIBE/EXPLAIN); everything that writes,
  alters, or has side effects is denied. It uses a `sqlglot` AST walk (the
  PDF mandates AST) plus a keyword guard for file-access primitives the
  parser silently drops (see below). The principle is deny-by-default: only
  known read-only shapes/verbs pass.
* `enforce_limit(sql, row_limit)` — appends or rewrites the trailing
  LIMIT clause so the connector requests `row_limit + 1` rows (the +1
  lets the connector detect truncation).

The connector still runs every statement inside a read-only transaction
with a hard timeout as a defence-in-depth layer.

Why AST *and* a keyword scan: sqlglot parses structure well — it catches
DML/DDL as proper nodes at top level and inside CTE bodies, and it splits
chained statements — but it **silently discards/mangles** constructs it can't
place in the tree: `SELECT ... INTO OUTFILE '/path'` re-renders to just
`SELECT ...`, `COPY TO PROGRAM` becomes a table alias, and DML inside a
FROM-subquery (`SELECT * FROM (DELETE FROM x) t`) collapses to `(DELETE)` with
no Delete node. Those clauses still reach the database, so the AST walk alone
is not enough. A token scan on the comment-stripped source (the same set the
pre-sqlglot regex guard used) backstops them, and the connector's read-only
transaction is the final layer.
"""
import re

from sqlglot import exp, parse
from sqlglot.errors import ParseError, TokenError

from tfm_rag.domain.errors.chat import UnsafeSQLError

# --- AST: forbidden expression node types -----------------------------------
# DDL/DML nodes are illegal anywhere in the tree (top level, CTE body,
# subquery). `Into` covers `SELECT ... INTO DUMPFILE`/`INTO <table>`.
# NOTE: `exp.Command` is deliberately NOT here. sqlglot parses statements it
# does not model (SHOW, EXPLAIN, and unknown verbs alike) as a `Command`, so
# blanket-rejecting it would also block legitimate read-only introspection.
# Instead, `Command` is gated by an explicit read-verb allowlist in the
# top-level check below (deny-by-default: only SHOW/EXPLAIN pass), which keeps
# unknown verbs rejected while letting introspection through.
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter,
    exp.Create, exp.TruncateTable, exp.Into,
    exp.Set, exp.Use, exp.Grant, exp.Merge, exp.Analyze,
)

# Read-only `Command` verbs that sqlglot cannot model but are safe: they read
# metadata / query plans and never mutate data. EXPLAIN ANALYZE (which DOES
# execute) is still blocked upstream by the ANALYZE banned-token scan.
_READ_ONLY_COMMAND_VERBS = frozenset({"SHOW", "EXPLAIN"})

# Side-effecting / file-access functions, matched on the Anonymous func name.
_FORBIDDEN_FUNCTIONS = {
    "pg_sleep", "sleep", "load_file", "lo_import", "lo_export",
    "dblink", "pg_read_file", "pg_ls_dir",
}

# --- Keyword guard: backstop for clauses sqlglot drops/mangles on parse ------
# sqlglot silently discards DDL/DML it can't place in the parse tree:
#   - `SELECT ... INTO OUTFILE '/p'` re-renders to plain `SELECT ...`
#   - `COPY TO PROGRAM` becomes a table alias
#   - DML inside a FROM-subquery (`SELECT * FROM (DELETE FROM x) t`) is
#     mangled to `(DELETE)` with NO Delete node in the walk
# All of those still reach the database, so the AST walk alone is not enough.
# We scan the comment-stripped original for the same banned tokens the
# pre-sqlglot regex guard used. Verified to have zero false positives on the
# legitimate SELECT corpus, and the connector's read-only transaction is the
# final backstop.
_BANNED_TOKEN_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|"
    r"REPLACE|MERGE|CALL|EXEC|EXECUTE|VACUUM|ANALYZE|"
    r"OUTFILE|DUMPFILE|LOAD_FILE|COPY)\b",
    re.IGNORECASE,
)

# Comment / string-literal strippers so the keyword scan can't be evaded
# (`OUT/**/FILE` → `OUTFILE`) and doesn't false-positive on string contents.
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_COMMENT_RE = re.compile(r"--[^\n]*")
_STRING_LITERAL_RE = re.compile(r"'[^']*'")


def _strip_comments_and_strings(sql: str) -> str:
    """Remove SQL comments and string literals so keyword scanning doesn't
    false-positive on content inside comments/strings — and so split tokens
    rejoin (`OUT/**/FILE` → `OUTFILE`) instead of slipping past the scan.
    """
    sql = _BLOCK_COMMENT_RE.sub("", sql)
    sql = _COMMENT_RE.sub("", sql)
    sql = _STRING_LITERAL_RE.sub("''", sql)
    return sql


def assert_read_only(sql: str) -> None:
    """Raise UnsafeSQLError unless `sql` is a single read-only statement.

    Read-only = reads data or metadata, never writes/alters/executes side
    effects. Rules:
      * Parses cleanly as exactly one statement (rejects empty, malformed,
        and chained/multi-statement SQL).
      * No DDL/DML node anywhere in the AST (catches top-level mutations,
        CTE-body DML, and subquery DML).
      * No side-effecting/file-access function calls.
      * No MySQL/Postgres file-access clause (OUTFILE/DUMPFILE/LOAD_FILE/COPY)
        nor mutating verb (INSERT/UPDATE/…/ANALYZE), scanned on the
        comment-stripped source because sqlglot drops/mangles some of them.
      * The top-level statement is a SELECT-family query (SELECT/UNION/WITH/
        sub-select) or a read-only introspection statement (DESCRIBE, or a
        SHOW/EXPLAIN Command). Anything else is denied by default.
    """
    if not sql or not sql.strip():
        raise UnsafeSQLError("empty SQL is not allowed")

    # Keyword guard FIRST — these tokens survive into execution even when
    # sqlglot drops/mangles them on parse, so the AST walk below cannot be
    # relied on to catch them.
    cleaned = _strip_comments_and_strings(sql)
    banned = _BANNED_TOKEN_RE.search(cleaned)
    if banned is not None:
        raise UnsafeSQLError(
            f"banned SQL token detected: {banned.group(0).upper()}"
        )

    try:
        parsed = parse(sql, error_level="immediate")
    except (ParseError, TokenError) as exc:
        raise UnsafeSQLError(f"could not parse SQL safely: {str(exc)[:120]}") from exc

    statements = [s for s in parsed if s is not None]
    if not statements:
        raise UnsafeSQLError("empty SQL is not allowed")
    if len(statements) > 1:
        raise UnsafeSQLError("multi-statement SQL is not allowed")

    stmt = statements[0]

    # Walk the whole tree: no DDL/DML node and no forbidden function at any depth.
    for node in stmt.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise UnsafeSQLError(
                f"banned SQL statement detected: {type(node).__name__.upper()}"
            )
        if isinstance(node, exp.Anonymous):
            name = (node.name or "").lower()
            if name in _FORBIDDEN_FUNCTIONS:
                raise UnsafeSQLError(f"banned SQL function detected: {name.upper()}")

    # The top-level statement must be read-only: a SELECT-family query
    # (SELECT / UNION / WITH … SELECT / parenthesised sub-select) or a
    # read-only introspection statement (DESCRIBE, or a SHOW/EXPLAIN Command).
    # Everything else is denied by default.
    if isinstance(stmt, (exp.Select, exp.Union, exp.With, exp.Subquery, exp.Describe)):
        return
    if (
        isinstance(stmt, exp.Command)
        and str(stmt.this or "").strip().upper() in _READ_ONLY_COMMAND_VERBS
    ):
        return
    raise UnsafeSQLError(
        f"only read-only statements are allowed (SELECT/WITH/UNION, "
        f"SHOW/DESCRIBE/EXPLAIN); got {type(stmt).__name__.upper()}"
    )


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
