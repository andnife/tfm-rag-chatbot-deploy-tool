#!/usr/bin/env python3
"""Validate a *testing dataset* (new datasets-as-entity format) end to end.

Unlike scripts/validate-dataset.py (which targets the legacy eval/schema.json
with metadata.source + always-present contexts/sql), this validates the format
used by eval/testing-datasets/<name>/, i.e. the rows imported by the /admin/eval
Datasets panel: top-level `source_doc`, nullable `sql_reference`, and per-scenario
shape (doc_only/sql_only/mixed/abstain).

It checks three things, all WITHOUT Docker (SQL runs in an in-memory sqlite DB
loaded from seed.sql):

  1. STRUCTURE  — required fields, enums, and per-scenario invariants
  2. CONTEXTS   — every reference_contexts string is an EXACT substring of its
                  source_doc article under docs/
  3. SQL        — every sql_reference executes against the seed and returns rows;
                  for COUNT/scalar queries, the returned value is checked to
                  appear in ground_truth (best effort)

Usage:
    python scripts/validate-testing-dataset.py                       # defaults to world-countries
    python scripts/validate-testing-dataset.py eval/testing-datasets/world-countries

Exit code 0 if everything passes, 1 otherwise (per-issue lines printed).
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "eval" / "testing-datasets" / "world-countries"

SCENARIOS = {"doc_only", "sql_only", "mixed", "abstain"}
COMPLEXITY = {"factual", "inferencial", "comparativa"}

G = "\033[32m"; R = "\033[31m"; Y = "\033[33m"; DIM = "\033[2m"; B = "\033[1m"; X = "\033[0m"


def _load_seed_into_sqlite(seed_sql: str) -> sqlite3.Connection:
    """Load a (simple, MySQL-dialect) DDL+INSERT seed into in-memory sqlite."""
    conn = sqlite3.connect(":memory:")
    # sqlite tolerates INT/BIGINT/VARCHAR/DECIMAL/TINYINT; strip trailing
    # MySQL-only table options just in case (ENGINE=, DEFAULT CHARSET=...).
    cleaned = re.sub(r"\)\s*ENGINE=[^;]*;", ");", seed_sql, flags=re.I)
    conn.executescript(cleaned)
    return conn


def _norm(s: str) -> str:
    """Light normalization for substring fallback: drop zero-width, collapse ws."""
    return re.sub(r"\s+", " ", s.replace("​", "")).strip()


def main(argv: list[str]) -> int:
    ds_dir = Path(argv[1]) if len(argv) > 1 else DEFAULT
    if not ds_dir.exists():
        print(f"No existe el directorio del dataset: {ds_dir}", file=sys.stderr)
        return 2

    rows_path = ds_dir / "rows.jsonl"
    docs_dir = ds_dir / "docs"
    seed_path = ds_dir / "seed.sql"

    rows = [json.loads(l) for l in rows_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    docs = {p.name: p.read_text(encoding="utf-8") for p in docs_dir.glob("*.txt")}
    docs_norm = {k: _norm(v) for k, v in docs.items()}

    conn = None
    if seed_path.exists():
        try:
            conn = _load_seed_into_sqlite(seed_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"{R}No se pudo cargar seed.sql en sqlite:{X} {exc}", file=sys.stderr)

    issues: list[str] = []
    counts: dict[str, int] = {}

    for i, r in enumerate(rows, start=1):
        sc = r.get("scenario")
        counts[sc] = counts.get(sc, 0) + 1
        loc = f"fila {i:>3} [{sc}]"

        # ---- 1. STRUCTURE ----
        for f in ("question", "ground_truth", "scenario", "complexity"):
            if not r.get(f):
                issues.append(f"{loc}: falta o vacío el campo '{f}'")
        if sc not in SCENARIOS:
            issues.append(f"{loc}: scenario desconocido '{sc}'")
        if r.get("complexity") not in COMPLEXITY:
            issues.append(f"{loc}: complexity desconocida '{r.get('complexity')}'")

        ctxs = r.get("reference_contexts") or []
        sql = r.get("sql_reference")
        src = r.get("source_doc")

        if sc in ("doc_only", "mixed"):
            if not ctxs:
                issues.append(f"{loc}: doc/mixed sin reference_contexts")
            if not src:
                issues.append(f"{loc}: doc/mixed sin source_doc")
        if sc in ("sql_only", "mixed"):
            if not sql:
                issues.append(f"{loc}: sql/mixed sin sql_reference")
        if sc == "doc_only" and sql:
            issues.append(f"{loc}: doc_only no debería llevar sql_reference")
        if sc == "abstain":
            if ctxs or sql:
                issues.append(f"{loc}: abstain debería no tener contextos ni sql")

        # ---- 2. CONTEXTS are verbatim substrings of the source article ----
        if ctxs and src:
            if src not in docs:
                issues.append(f"{loc}: source_doc '{src}' no está en docs/")
            else:
                art, artn = docs[src], docs_norm[src]
                for j, c in enumerate(ctxs):
                    if c in art:
                        continue
                    if _norm(c) in artn:
                        issues.append(f"{loc}: ctx[{j}] coincide solo tras normalizar "
                                      f"(espacios/zero-width) — revisar")
                    else:
                        issues.append(f"{loc}: ctx[{j}] NO es substring de {src}: "
                                      f"{DIM}{c[:70]!r}…{X}")

        # ---- 3. SQL executes against the seed ----
        if sql and conn is not None:
            try:
                cur = conn.execute(sql)
                res = cur.fetchall()
            except Exception as exc:  # noqa: BLE001
                issues.append(f"{loc}: SQL falla: {exc} {DIM}<< {sql}{X}")
            else:
                if not res:
                    issues.append(f"{loc}: SQL no devuelve filas {DIM}<< {sql}{X}")
                else:
                    # best-effort: a scalar result should appear in ground_truth.
                    # Strip thousands separators (spaces incl. NBSP/thin, '.', ',')
                    # that sit BETWEEN digits, so "608 500 000" matches 608500000.
                    if len(res) == 1 and len(res[0]) == 1:
                        val = str(res[0][0])
                        gt = r.get("ground_truth", "")
                        gt_digits = re.sub(r"(?<=\d)[\s.,  ](?=\d)", "", gt)
                        if val.lstrip("-").isdigit() and re.search(r"\d", gt) and val not in gt_digits:
                            issues.append(f"{loc}: {Y}SQL devuelve {val} pero ground_truth "
                                          f"no lo menciona{X} {DIM}({gt[:60]}…){X}")

    # ---- report ----
    print(f"{B}Dataset:{X} {ds_dir.relative_to(ROOT) if ds_dir.is_relative_to(ROOT) else ds_dir}")
    print(f"{B}Filas:{X} {len(rows)}  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"{B}Docs:{X} {len(docs)}   {B}seed.sql:{X} {'cargado' if conn else 'ausente/no cargado'}")
    print("─" * 70)
    if not issues:
        print(f"{G}{B}✅ TODO OK{X} — estructura, contextos verbatim y SQL válidos.")
        return 0
    print(f"{R}{B}❌ {len(issues)} incidencia(s):{X}")
    for it in issues:
        print(f"  {it}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
