#!/usr/bin/env python3
"""Retrospective SQL-safety + metric-validity audit of the evaluation logs.

Runs EVERY SQL statement the chatbot generated during the (already executed)
evaluation campaign back through the *current, consolidated* read-only gate
(`sql_safety.assert_read_only`) and cross-tabulates two things per statement:

  1. What the campaign actually DID with it (campaign outcome):
       - executed_ok    : ran against the DB (row_count is not None)
       - rejected_gate  : blocked by the campaign-era SQL gate (UnsafeSQLError)
       - db_error       : reached the DB but errored / timed out
  2. What the EVOLVED gate would decide now (allow / reject).

Two questions this answers:

  * SECURITY (§6.5): of the statements that *actually executed*, did any
    perform a write / side effect? Under a read-only gate that means: does the
    evolved gate flag any executed statement as unsafe? Expected: 0.

  * METRIC VALIDITY: where would the evolved system behave differently from the
    campaign, so that the reported metrics may not transfer 1:1?
       - REGRESSION  : executed_ok in the campaign, but the evolved gate would
                       REJECT it → that case would now fail/retry (metric may be
                       optimistic there).
       - IMPROVEMENT : rejected by the campaign-era gate, but the evolved gate
                       would ALLOW it (e.g. SHOW/DESCRIBE introspection) → that
                       case would now explore further (metric may be conservative).

The evolved gate is frozen before this audit runs (it was designed from the
"deny writes, allow reads" principle and locked by unit tests), so this is a
genuine after-the-fact check, not a gate tuned to fit the logs.

Usage:
    .venv/bin/python scripts/audit-eval-sql.py [EVAL_RUNS_DIR] [--out REPORT.md]

Exit code is non-zero only if a SECURITY violation is found (an executed
statement the read-only gate rejects), so it can gate CI.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

# sqlglot logs a WARNING every time it falls back to a `Command` node (e.g. for
# every SHOW/EXPLAIN). That is expected here and would drown the audit output.
logging.getLogger("sqlglot").setLevel(logging.ERROR)
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# --- make the application package importable --------------------------------
_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND / "src"))

from tfm_rag.application.chat.sql_safety import assert_read_only  # noqa: E402
from tfm_rag.domain.errors.chat import UnsafeSQLError  # noqa: E402


# --- classification ----------------------------------------------------------

CAMPAIGN_EXECUTED = "executed_ok"
CAMPAIGN_REJECTED = "rejected_gate"
CAMPAIGN_DB_ERROR = "db_error"


def classify_campaign_outcome(iteration: dict) -> str:
    """What did the campaign do with this SQL, per the logged iteration?"""
    if iteration.get("row_count") is not None:
        return CAMPAIGN_EXECUTED
    preview = str(iteration.get("result_preview") or "")
    if "UnsafeSQLError" in preview:
        return CAMPAIGN_REJECTED
    return CAMPAIGN_DB_ERROR


def evolved_verdict(sql: str) -> tuple[bool, str]:
    """Run the current read-only gate. Returns (allowed, reason)."""
    try:
        assert_read_only(sql)
        return True, ""
    except UnsafeSQLError as exc:
        return False, str(exc)


@dataclass
class Occurrence:
    run_id: str
    case_idx: object
    scenario: str
    question: str
    sql: str
    campaign: str
    allowed: bool
    reason: str


@dataclass
class Audit:
    occurrences: list[Occurrence] = field(default_factory=list)
    runs_scanned: int = 0
    cases_scanned: int = 0

    @property
    def total_sql(self) -> int:
        return len(self.occurrences)

    @property
    def unique_sql(self) -> set[str]:
        return {o.sql for o in self.occurrences}

    def crosstab(self) -> Counter:
        return Counter((o.campaign, "allow" if o.allowed else "reject") for o in self.occurrences)

    # findings ----------------------------------------------------------------
    def security_violations(self) -> list[Occurrence]:
        # Executed against the DB, yet the read-only gate rejects it.
        return [o for o in self.occurrences if o.campaign == CAMPAIGN_EXECUTED and not o.allowed]

    def regressions(self) -> list[Occurrence]:
        # Executed OK in the campaign but the evolved gate would reject it.
        # (Same predicate as security_violations, surfaced under the
        # metric-validity lens — every regression is also a thing to explain.)
        return [o for o in self.occurrences if o.campaign == CAMPAIGN_EXECUTED and not o.allowed]

    def improvements(self) -> list[Occurrence]:
        # Rejected by the campaign gate but the evolved gate would allow it.
        return [o for o in self.occurrences if o.campaign == CAMPAIGN_REJECTED and o.allowed]

    def consistently_rejected(self) -> list[Occurrence]:
        # Rejected by BOTH the campaign gate and the evolved gate (genuinely
        # non-read or unparseable → fail-safe). Documented for completeness so
        # every cell of the cross-tab is accounted for.
        return [o for o in self.occurrences if o.campaign == CAMPAIGN_REJECTED and not o.allowed]


def _iter_cases(run_dir: Path):
    """Yield case dicts for a run, preferring trace.jsonl, falling back to report.json."""
    trace = run_dir / "trace.jsonl"
    if trace.exists():
        for line in trace.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
        return
    report = run_dir / "report.json"
    if report.exists():
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        yield from data.get("cases", []) or []


def run_audit(eval_runs_dir: Path) -> Audit:
    audit = Audit()
    for run_dir in sorted(p for p in eval_runs_dir.iterdir() if p.is_dir()):
        has_cases = False
        for case in _iter_cases(run_dir):
            has_cases = True
            audit.cases_scanned += 1
            case_idx = case.get("idx", case.get("index"))
            scenario = str(case.get("scenario") or "")
            question = str(case.get("question") or "")
            for it in case.get("iterations", []) or []:
                sql = it.get("sql")
                if not sql or not str(sql).strip():
                    continue
                sql = str(sql)
                campaign = classify_campaign_outcome(it)
                allowed, reason = evolved_verdict(sql)
                audit.occurrences.append(
                    Occurrence(
                        run_id=run_dir.name,
                        case_idx=case_idx,
                        scenario=scenario,
                        question=question,
                        sql=sql,
                        campaign=campaign,
                        allowed=allowed,
                        reason=reason,
                    )
                )
        if has_cases:
            audit.runs_scanned += 1
    return audit


# --- reporting ---------------------------------------------------------------

def _group_by_case(occs: list[Occurrence]) -> dict:
    grouped: dict = defaultdict(list)
    for o in occs:
        grouped[(o.run_id, o.case_idx, o.scenario)].append(o)
    return grouped


def render_markdown(audit: Audit) -> str:
    ct = audit.crosstab()
    sec = audit.security_violations()
    reg = audit.regressions()
    imp = audit.improvements()
    both = audit.consistently_rejected()

    def cell(campaign: str, verdict: str) -> int:
        return ct.get((campaign, verdict), 0)

    lines: list[str] = []
    lines.append("# Auditoría retrospectiva de seguridad SQL + validez de métricas")
    lines.append("")
    lines.append(
        "Cada consulta SQL generada durante la campaña de evaluación se reevaluó "
        "contra el gate read-only consolidado actual (`sql_safety.assert_read_only`). "
        "El gate se congeló **antes** de esta auditoría (diseñado por el principio "
        "\"denegar escrituras, permitir lecturas\" y fijado con tests unitarios)."
    )
    lines.append("")
    lines.append("## Alcance")
    lines.append("")
    lines.append(f"- Runs analizados: **{audit.runs_scanned}**")
    lines.append(f"- Casos analizados: **{audit.cases_scanned}**")
    lines.append(f"- Sentencias SQL (ocurrencias): **{audit.total_sql}**")
    lines.append(f"- Sentencias SQL únicas: **{len(audit.unique_sql)}**")
    lines.append("")
    lines.append("## Tabla cruzada — resultado en campaña × veredicto del gate evolucionado")
    lines.append("")
    lines.append("| Resultado en campaña | Gate ALLOW | Gate REJECT |")
    lines.append("|---|---:|---:|")
    lines.append(
        f"| Ejecutada contra la BD (`executed_ok`) | {cell(CAMPAIGN_EXECUTED,'allow')} | "
        f"{cell(CAMPAIGN_EXECUTED,'reject')} |"
    )
    lines.append(
        f"| Rechazada por el gate de campaña (`rejected_gate`) | {cell(CAMPAIGN_REJECTED,'allow')} | "
        f"{cell(CAMPAIGN_REJECTED,'reject')} |"
    )
    lines.append(
        f"| Error de BD / timeout (`db_error`) | {cell(CAMPAIGN_DB_ERROR,'allow')} | "
        f"{cell(CAMPAIGN_DB_ERROR,'reject')} |"
    )
    lines.append("")

    # SECURITY --------------------------------------------------------------
    lines.append("## 1. Seguridad (§6.5): ¿se ejecutó alguna operación no-lectura?")
    lines.append("")
    executed = cell(CAMPAIGN_EXECUTED, "allow") + cell(CAMPAIGN_EXECUTED, "reject")
    if not sec:
        lines.append(
            f"✅ **0 violaciones.** De las **{executed}** sentencias que se ejecutaron "
            f"realmente contra la base de datos durante la campaña, el gate read-only "
            f"consolidado las clasifica **todas** como de solo lectura. Ninguna operación "
            f"de escritura/modificación/borrado ni con efectos colaterales llegó a ejecutarse."
        )
    else:
        lines.append(
            f"❌ **{len(sec)} violación(es):** sentencias que se ejecutaron contra la BD "
            f"pero que el gate read-only rechaza (posible escritura ejecutada o falso "
            f"positivo del gate a investigar):"
        )
        lines.append("")
        for o in sec:
            lines.append(f"- `{o.run_id}` caso {o.case_idx} [{o.scenario}] — {o.reason}")
            lines.append(f"  - `{o.sql}`")
    lines.append("")

    # METRIC VALIDITY: regressions -----------------------------------------
    lines.append("## 2. Validez de métricas — REGRESIONES (métrica posiblemente optimista)")
    lines.append("")
    lines.append(
        "Sentencias que **se ejecutaron con éxito** en la campaña pero que el gate "
        "evolucionado **rechazaría** ahora. En el sistema evolucionado esos casos "
        "fallarían/reintentarían, por lo que su métrica podría no transferirse."
    )
    lines.append("")
    if not reg:
        lines.append(
            "✅ **Ninguna.** Toda consulta que se ejecutó en la campaña sigue siendo "
            "aceptada por el gate evolucionado: las métricas de esos casos se conservan."
        )
    else:
        grouped = _group_by_case(reg)
        lines.append(f"⚠️ **{len(reg)} ocurrencia(s)** en **{len(grouped)} caso(s)**:")
        lines.append("")
        for (run_id, case_idx, scenario), occs in grouped.items():
            lines.append(f"- `{run_id}` caso {case_idx} [{scenario}] — {occs[0].question[:100]}")
            for o in occs:
                lines.append(f"  - _{o.reason}_ · `{o.sql}`")
    lines.append("")

    # METRIC VALIDITY: improvements ----------------------------------------
    lines.append("## 3. Validez de métricas — MEJORAS (métrica posiblemente conservadora)")
    lines.append("")
    lines.append(
        "Sentencias que el gate de campaña **rechazó** (p.ej. introspección `SHOW`/"
        "`DESCRIBE`) pero que el gate evolucionado **permitiría**. En el sistema "
        "evolucionado esos casos explorarían el esquema y podrían responder mejor, "
        "por lo que la métrica de la campaña es, en esos casos, conservadora."
    )
    lines.append("")
    if not imp:
        lines.append("• Ninguna: el gate de campaña no rechazó nada que el gate evolucionado permita.")
    else:
        grouped = _group_by_case(imp)
        lines.append(f"⭐ **{len(imp)} ocurrencia(s)** en **{len(grouped)} caso(s)**:")
        lines.append("")
        for (run_id, case_idx, scenario), occs in grouped.items():
            lines.append(f"- `{run_id}` caso {case_idx} [{scenario}] — {occs[0].question[:100]}")
            for o in occs:
                lines.append(f"  - `{o.sql}`")
    lines.append("")

    # Completeness: statements rejected by both gates ----------------------
    lines.append("## 4. Rechazadas por ambos gates (fail-safe, sin cambio)")
    lines.append("")
    lines.append(
        "Cierra la tabla: sentencias que el gate de campaña **y** el evolucionado "
        "rechazan igual. No son escrituras: son intentos genuinamente no-lectura o "
        "SQL malformada que no parsea (rechazo *fail-safe*: si no se puede verificar, "
        "no se ejecuta)."
    )
    lines.append("")
    if not both:
        lines.append("• Ninguna.")
    else:
        lines.append(f"**{len(both)} ocurrencia(s):**")
        lines.append("")
        for o in both:
            lines.append(f"- `{o.run_id}` caso {o.case_idx} [{o.scenario}] — {o.reason}")
            lines.append(f"  - `{o.sql[:200]}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "eval_runs_dir",
        nargs="?",
        default=str(_BACKEND / "eval_runs"),
        help="directory containing per-run subdirs with trace.jsonl / report.json",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="path to write the markdown report (default: <eval_runs_dir>/SQL-SECURITY-AUDIT.md)",
    )
    args = parser.parse_args()

    eval_runs_dir = Path(args.eval_runs_dir)
    if not eval_runs_dir.is_dir():
        print(f"error: {eval_runs_dir} is not a directory", file=sys.stderr)
        return 2

    audit = run_audit(eval_runs_dir)
    report = render_markdown(audit)

    out = Path(args.out) if args.out else eval_runs_dir / "SQL-SECURITY-AUDIT.md"
    out.write_text(report, encoding="utf-8")

    sec = audit.security_violations()
    reg = audit.regressions()
    imp = audit.improvements()
    print(f"Scanned {audit.runs_scanned} runs / {audit.cases_scanned} cases / "
          f"{audit.total_sql} SQL statements ({len(audit.unique_sql)} unique).")
    print(f"Security violations : {len(sec)}")
    print(f"Regressions         : {len(reg)}")
    print(f"Improvements        : {len(imp)}")
    print(f"Report written to   : {out}")
    return 1 if sec else 0


if __name__ == "__main__":
    raise SystemExit(main())
