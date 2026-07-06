"""Post-processing statistics over a loaded eval ``report.json``: bootstrap 95%
confidence intervals per metric and mean per-query latency. Pure functions, no I/O."""

from __future__ import annotations

import math
import random
from typing import Any


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return math.nan
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = pct / 100.0 * (len(sorted_values) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return sorted_values[lo]
    frac = rank - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def bootstrap_ci(
    values: list[float],
    n_resamples: int = 1000,
    seed: int = 12345,
    ci: float = 0.95,
) -> tuple[float, float, float]:
    """Return ``(mean, lower, upper)`` for a ``ci`` bootstrap CI of the mean.
    Reproducible for a fixed ``seed``. NaN/None values are dropped."""
    clean = [float(v) for v in values if v is not None and not math.isnan(float(v))]
    n = len(clean)
    if n == 0:
        return (math.nan, math.nan, math.nan)
    mean = sum(clean) / n
    if n == 1:
        return (mean, clean[0], clean[0])
    rng = random.Random(seed)  # noqa: S311 - stats resampling, not cryptographic use
    means = [
        sum(clean[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(n_resamples)
    ]
    means.sort()
    tail = (1.0 - ci) / 2.0 * 100.0
    return (mean, _percentile(means, tail), _percentile(means, 100.0 - tail))


def _metric_names(cases: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for c in cases:
        for k in (c.get("scores") or {}):
            if k not in names:
                names.append(k)
    return names


def _metric_values(cases: list[dict[str, Any]], metric: str) -> list[float]:
    out: list[float] = []
    for c in cases:
        scores = c.get("scores")
        if not scores or metric not in scores:
            continue
        v = scores[metric]
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if not math.isnan(fv):
            out.append(fv)
    return out


def _metrics_block(cases: list[dict[str, Any]], n_resamples: int, seed: int) -> dict[str, Any]:
    block: dict[str, Any] = {}
    for metric in _metric_names(cases):
        values = _metric_values(cases, metric)
        mean, lower, upper = bootstrap_ci(values, n_resamples=n_resamples, seed=seed)
        block[metric] = {"mean": mean, "ci_lower": lower, "ci_upper": upper, "n": len(values)}
    return block


def _latency_block(cases: list[dict[str, Any]]) -> dict[str, Any]:
    lats: list[float] = []
    for c in cases:
        v = c.get("total_latency_ms")
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if not math.isnan(fv):
            lats.append(fv)
    if not lats:
        return {"mean_ms": math.nan, "n": 0}
    return {"mean_ms": sum(lats) / len(lats), "n": len(lats)}


def summarize_report(
    report: dict[str, Any],
    n_resamples: int = 1000,
    seed: int = 12345,
) -> dict[str, Any]:
    """Per-metric mean + bootstrap 95% CI and mean per-query latency, overall and
    per scenario, from a loaded ``report.json`` dict."""
    cases = report.get("cases", []) or []
    result: dict[str, Any] = {
        "metrics": _metrics_block(cases, n_resamples, seed),
        "latency": _latency_block(cases),
        "per_scenario": {},
    }
    scenarios: list[str] = []
    for c in cases:
        s = c.get("scenario")
        if s and s not in scenarios:
            scenarios.append(s)
    for s in scenarios:
        scoped = [c for c in cases if c.get("scenario") == s]
        result["per_scenario"][s] = {
            "metrics": _metrics_block(scoped, n_resamples, seed),
            "latency": _latency_block(scoped),
        }
    return result
