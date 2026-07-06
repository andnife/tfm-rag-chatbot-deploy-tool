import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from tfm_rag.domain.catalog.eval_metrics import RagasMetric
from tfm_rag.domain.value_objects.evaluation_report import EvaluationReport


@dataclass(frozen=True, slots=True)
class ReportPaths:
    json_path: Path
    markdown_path: Path


_REPORTED_METRICS = (
    RagasMetric.FAITHFULNESS,
    RagasMetric.ANSWER_RELEVANCY,
    RagasMetric.CONTEXT_PRECISION,
    RagasMetric.CONTEXT_RECALL,
)


def _format_markdown(report: EvaluationReport) -> str:
    lines: list[str] = []
    lines.append(f"# Evaluation report — {report.chatbot_name}")
    lines.append("")
    lines.append(f"- Chatbot ID: `{report.chatbot_id}`")
    lines.append(f"- Dataset: `{report.dataset_path}`")
    lines.append(f"- Scenario filter: `{report.scenario_filter or '*'}`")
    lines.append(f"- Generator model: `{report.generator_model or '—'}`")
    lines.append(f"- Judge model: `{report.ragas_judge_model}`")
    lines.append(f"- Run start: `{report.run_started_at.isoformat()}`")
    lines.append(f"- Run end: `{report.run_finished_at.isoformat()}`")
    lines.append("")
    lines.append(
        f"**Cases:** {report.summary.num_cases} total, "
        f"{report.summary.num_scored} scored, "
        f"{report.summary.num_errors} errored."
    )
    lines.append("")
    lines.append("## Summary metrics")
    lines.append("")
    lines.append("| Metric | Score |")
    lines.append("| --- | --- |")
    for metric in _REPORTED_METRICS:
        value = report.summary.metrics.get(metric)
        cell = f"{value:.3f}" if value is not None else "-"
        lines.append(f"| {metric} | {cell} |")
    lines.append("")

    for metric in _REPORTED_METRICS:
        top = report.top_failures(metric=metric, n=3)
        if not top:
            continue
        lines.append(f"## Top failures by {metric}")
        lines.append("")
        for case in top:
            score = (case.scores or {}).get(metric)
            score_cell = f"{score:.3f}" if score is not None else "-"
            preview = case.predicted_answer or "(no answer)"
            if len(preview) > 200:
                preview = preview[:200] + "..."
            lines.append(f"- **{score_cell}** — _Q:_ {case.question}")
            lines.append(f"  - GT: {case.ground_truth}")
            lines.append(f"  - A: {preview}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_report(
    report: EvaluationReport,
    *,
    output_dir: Path,
    timestamped: bool = True,
) -> ReportPaths:
    """Serialise a report to ``output_dir``.

    ``timestamped=True`` (default, used by the CLI) writes
    ``report_<ts>.json`` + ``.md`` to avoid silent overwrites.
    ``timestamped=False`` writes canonical ``report.json`` + ``report.md``
    (what the read-only reports viewer at ``eval_reports.py`` reads), used
    by the web eval-run job which already isolates each run in its own dir.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if timestamped:
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        json_path = output_dir / f"report_{ts}.json"
        md_path = output_dir / f"report_{ts}.md"
    else:
        json_path = output_dir / "report.json"
        md_path = output_dir / "report.md"

    json_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(_format_markdown(report), encoding="utf-8")
    return ReportPaths(json_path=json_path, markdown_path=md_path)
