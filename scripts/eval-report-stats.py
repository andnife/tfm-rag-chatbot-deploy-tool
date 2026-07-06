#!/usr/bin/env python3
"""Print bootstrap 95% CIs per metric + mean per-query latency from a report.json.

Usage:
    python scripts/eval-report-stats.py backend/eval_runs/<run>/report.json
    python scripts/eval-report-stats.py report.json --resamples 1000 --seed 12345
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the backend package importable (match the repo's existing script convention).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend" / "src"))

from tfm_rag.application.evaluation.report_stats import summarize_report  # noqa: E402


def _fmt(x: float) -> str:
    return "n/a" if x != x else f"{x:.4f}"  # x != x is True only for NaN


def _print_block(title: str, block: dict) -> None:
    print(f"## {title}")
    for metric, m in block["metrics"].items():
        print(
            f"  {metric:<20s} mean={_fmt(m['mean'])}  "
            f"95% CI [{_fmt(m['ci_lower'])}, {_fmt(m['ci_upper'])}]  (n={m['n']})"
        )
    lat = block["latency"]
    print(f"  {'latency_ms/query':<20s} mean={_fmt(lat['mean_ms'])}  (n={lat['n']})\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("report", help="path to a report.json produced by an eval run")
    ap.add_argument("--resamples", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=12345)
    args = ap.parse_args()

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    stats = summarize_report(report, n_resamples=args.resamples, seed=args.seed)

    print(f"# Eval report stats — resamples={args.resamples} seed={args.seed}\n")
    _print_block("Overall", stats)
    for scenario, block in stats["per_scenario"].items():
        _print_block(f"Scenario: {scenario}", block)


if __name__ == "__main__":
    main()
