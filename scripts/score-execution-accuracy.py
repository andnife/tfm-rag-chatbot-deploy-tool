#!/usr/bin/env python3
"""Add execution_accuracy to a report.json by re-executing generated vs reference SQL.

Usage:
    python scripts/score-execution-accuracy.py \
        backend/eval_runs/pipeline-esc-2/report.json eval/testing-datasets/world-countries/rows.jsonl
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import asyncmy

# Import the pure helpers from the backend package (venv must be active).
from tfm_rag.application.evaluation.execution_accuracy import execution_accuracy  # noqa: E402

DB = {
    "host": os.environ.get("MYSQL_HOST", "localhost"),
    "port": int(os.environ.get("MYSQL_PORT", "3306")),
    "user": os.environ.get("MYSQL_ROOT_USER", "root"),
    "password": os.environ.get("MYSQL_ROOT_PASSWORD", "rootpw"),
    "database": os.environ.get("MYSQL_DATABASE", "tfm_rag_source_test"),
}


def _last_sql(case: dict) -> str | None:
    attempts = (case.get("routing_trace") or {}).get("attempts") or []
    sqls = [a.get("sql") for a in attempts if a.get("sql")]
    return sqls[-1] if sqls else None


async def _run(cur, sql: str) -> list[dict]:
    await cur.execute("START TRANSACTION READ ONLY")
    try:
        await cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in await cur.fetchall()]
    finally:
        await cur.execute("ROLLBACK")
    return rows


async def main() -> None:
    report_path = Path(sys.argv[1])
    dataset_path = Path(sys.argv[2])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    refs = {}
    with dataset_path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                obj = json.loads(line)
                refs[obj["question"].strip()] = obj.get("sql_reference")

    conn = await asyncmy.connect(**DB)
    scored = 0
    async with conn.cursor() as cur:
        for case in report["cases"]:
            ref_sql = refs.get(case["question"].strip())
            gen_sql = _last_sql(case)
            if not ref_sql or not gen_sql:
                continue
            try:
                ref_rows = await _run(cur, ref_sql)
                gen_rows = await _run(cur, gen_sql)
            except Exception as exc:
                print(f"SQL error for case {case.get('question')!r}: {exc}")
                case.setdefault("scores", {})
                case["scores"]["execution_accuracy"] = 0.0
                scored += 1
                continue
            case.setdefault("scores", {})
            case["scores"]["execution_accuracy"] = execution_accuracy(gen_rows, ref_rows)
            scored += 1
    await conn.ensure_closed()

    # Recompute the scenario mean for execution_accuracy.
    vals = [c["scores"]["execution_accuracy"] for c in report["cases"]
            if c.get("scores") and "execution_accuracy" in c["scores"]]
    if vals:
        report["summary"].setdefault("metrics", {})
        report["summary"]["metrics"]["execution_accuracy"] = sum(vals) / len(vals)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Scored execution_accuracy on {scored} cases; mean over {len(vals)} = "
          f"{(sum(vals)/len(vals)) if vals else 'n/a'}")


if __name__ == "__main__":
    asyncio.run(main())
