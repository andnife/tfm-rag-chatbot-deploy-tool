import pytest

from tfm_rag.application.evaluation.seed_sql import (
    assert_safe_seed,
    split_sql_statements,
)
from tfm_rag.domain.errors.evaluation import EvalDatasetError


def test_split_drops_comments_and_blank_statements() -> None:
    sql = (
        "-- seed file\n"
        "CREATE TABLE products (id INT PRIMARY KEY, name TEXT);\n"
        "\n"
        "INSERT INTO products VALUES (1, 'Desk');\n"
        ";\n"
    )
    stmts = split_sql_statements(sql)
    assert len(stmts) == 2
    assert stmts[0].upper().startswith("CREATE TABLE")
    assert stmts[1].upper().startswith("INSERT")


def test_assert_safe_seed_allows_ddl_and_insert() -> None:
    assert_safe_seed([
        "CREATE TABLE orders (id INT)",
        "INSERT INTO orders VALUES (1)",
        "CREATE INDEX ix ON orders (id)",
    ])


@pytest.mark.parametrize("bad", [
    "DROP DATABASE evalds_x",
    "drop schema foo",
    "CREATE DATABASE other",
    "CREATE USER 'x'@'%'",
    "GRANT ALL ON *.* TO 'x'",
    "REVOKE ALL ON *.* FROM 'x'",
    "SELECT load_file('/etc/passwd')",
    "SELECT * FROM t INTO OUTFILE '/tmp/x'",
    "SELECT * FROM t INTO DUMPFILE '/tmp/x'",
    "CREATE SCHEMA other",
    "USE mysql",
])
def test_assert_safe_seed_rejects_dangerous(bad: str) -> None:
    with pytest.raises(EvalDatasetError):
        assert_safe_seed([bad])
