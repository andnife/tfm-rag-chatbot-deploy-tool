import re

from tfm_rag.domain.errors.evaluation import EvalDatasetError

# Forbidden patterns (case-insensitive, matched against each statement).
# Seed provisioning controls the database lifecycle itself; the user-supplied
# seed may only define/populate tables inside the dataset's own schema.
_FORBIDDEN = [
    (re.compile(r"\bdrop\s+(database|schema)\b", re.I), "DROP DATABASE/SCHEMA"),
    (re.compile(r"\bcreate\s+(database|schema)\b", re.I), "CREATE DATABASE/SCHEMA"),
    (re.compile(r"\bcreate\s+user\b", re.I), "CREATE USER"),
    (re.compile(r"\bgrant\b", re.I), "GRANT"),
    (re.compile(r"\brevoke\b", re.I), "REVOKE"),
    (re.compile(r"\bload_file\s*\(", re.I), "LOAD_FILE"),
    (re.compile(r"\binto\s+(outfile|dumpfile)\b", re.I), "INTO OUTFILE/DUMPFILE"),
    (re.compile(r"^\s*use\b", re.I), "USE (database switch)"),
]


def split_sql_statements(sql: str) -> list[str]:
    """Split a multi-statement seed into individual statements.

    Strips ``-- ...`` line comments, splits on ``;``, and drops blank
    statements. Sufficient for generated/curated seed files (DDL + INSERTs);
    does not attempt to parse string literals containing semicolons.
    """
    lines = [
        line for line in sql.splitlines()
        if not line.lstrip().startswith("--")
    ]
    cleaned = "\n".join(lines)
    out: list[str] = []
    for raw in cleaned.split(";"):
        stmt = raw.strip()
        if stmt:
            out.append(stmt)
    return out


def assert_safe_seed(statements: list[str]) -> None:
    for stmt in statements:
        for pattern, label in _FORBIDDEN:
            if pattern.search(stmt):
                raise EvalDatasetError(
                    f"seed contains forbidden statement ({label}): {stmt[:80]!r}"
                )
