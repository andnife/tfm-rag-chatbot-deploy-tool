#!/usr/bin/env python3
"""Verify the `sql_reference` of each eval dataset row against the seeded MySQL.

For every JSONL row that carries a non-empty `sql_reference`, the statement is
executed inside a **read-only transaction** against the source MySQL and the
result is classified:

    PASS   <n>   — ran and returned n>0 rows
    EMPTY  0     — ran but returned no rows (likely a bad ground truth)
    FAIL   <err> — raised an error (syntax, missing table, write attempt, …)
    NO_SQL       — row has no `sql_reference` (e.g. a doc_only row)

This is the *execution-accuracy* check the RAGAS pipeline can't do on its own
(`dataset_loader` discards `sql_reference`). Use it while curating a SQL-bearing
eval dataset: keep rows that PASS and whose natural-language `ground_truth` is
consistent with the returned rows; drop or fix FAIL/EMPTY.

Connection comes from env (source `infra/.env` first), with a DSN override:
    MYSQL_DSN   e.g. mysql://tfm:pass@localhost:3306/tfm_rag_source_test
or the discrete vars MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE / MYSQL_HOST /
MYSQL_PORT (defaults match the docker-compose seeded container).

Usage:
    python scripts/verify-sql-references.py eval/testing-datasets/world-countries/rows.jsonl
    # summary line goes to stderr; per-row TSV to stdout (pipe-friendly):
    python scripts/verify-sql-references.py <file> | grep -E "FAIL|EMPTY"

Exit code: 0 if every row is PASS or NO_SQL; 1 if any row is FAIL or EMPTY.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from urllib.parse import urlparse

import asyncmy


def _conn_params() -> dict[str, object]:
    dsn = os.environ.get("MYSQL_DSN")
    if dsn:
        p = urlparse(dsn)
        return {
            "host": p.hostname or "localhost",
            "port": p.port or 3306,
            "user": p.username or "tfm",
            "password": p.password or "",
            "database": (p.path or "").lstrip("/") or "tfm_rag_source_test",
        }
    return {
        "host": os.environ.get("MYSQL_HOST", "localhost"),
        "port": int(os.environ.get("MYSQL_PORT", "3306")),
        "user": os.environ.get("MYSQL_USER", "tfm"),
        "password": os.environ.get("MYSQL_PASSWORD", ""),
        "database": os.environ.get("MYSQL_DATABASE", "tfm_rag_source_test"),
    }


async def _verify(rows: list[dict]) -> int:
    conn = await asyncmy.connect(**_conn_params())
    counts = {"PASS": 0, "EMPTY": 0, "FAIL": 0, "NO_SQL": 0}
    try:
        for i, row in enumerate(rows, start=1):
            sql = (row.get("sql_reference") or "").strip()
            question = str(row.get("question", ""))[:60]
            if not sql:
                counts["NO_SQL"] += 1
                print(f"{i}\tNO_SQL\t\t{question}")
                continue
            async with conn.cursor() as cur:
                try:
                    # Read-only transaction: a dataset SQL that tries to write
                    # fails here exactly as it would in production.
                    await cur.execute("START TRANSACTION READ ONLY")
                    await cur.execute(sql)
                    fetched = await cur.fetchall()
                    await cur.execute("ROLLBACK")
                    n = len(fetched)
                    label = "EMPTY" if n == 0 else "PASS"
                    counts[label] += 1
                    print(f"{i}\t{label}\t{n}\t{question}")
                except Exception as exc:  # noqa: BLE001 — report, don't crash the run
                    with contextlib.suppress(Exception):
                        await cur.execute("ROLLBACK")
                    counts["FAIL"] += 1
                    print(f"{i}\tFAIL\t{str(exc)[:120]}\t{question}")
    finally:
        await conn.ensure_closed()

    total = sum(counts.values())
    print(
        f"\n{total} rows: {counts['PASS']} PASS, {counts['EMPTY']} EMPTY, "
        f"{counts['FAIL']} FAIL, {counts['NO_SQL']} NO_SQL",
        file=sys.stderr,
    )
    return 0 if counts["FAIL"] == 0 and counts["EMPTY"] == 0 else 1


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: verify-sql-references.py <path.jsonl>", file=sys.stderr)
        return 2
    with open(sys.argv[1]) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    return asyncio.run(_verify(rows))


if __name__ == "__main__":
    sys.exit(main())
