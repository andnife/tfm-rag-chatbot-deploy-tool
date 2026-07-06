"""Build the context the evaluator sees when routing.

Documents are listed as a lightweight signal: KB names + per-document labels.
C1 enriches each label via `doc_label` (filename + auto-generated description);
the orchestrator builds the labels and passes them here unchanged.

The SQL block here is DELIBERATELY light: the router only needs to know a SQL
database exists and roughly what it covers (table names) to pick a route. The
full column-level schema is expensive and is injected once inside the SQL
sub-route thread instead — never in the routing context. See
`render_sql_routing_hint`.
"""
from typing import Any

from tfm_rag.application.chat.system_prompt import _sanitize_identifier


def doc_label(*, filename: str, description: str | None) -> str:
    """Format one document's routing label: 'filename — description' when a
    description exists, else just the filename (C1 seam)."""
    if description and description.strip():
        return f"{filename} — {description.strip()}"
    return filename


def render_sql_routing_hint(db_sources: list[dict[str, Any]]) -> str:
    """A token-cheap SQL signal for the router: source id + driver/db + the
    TABLE NAMES only (no columns). Columns belong in the SQL sub-route thread,
    not here — the router just needs to know SQL exists and its topic."""
    db_only = [s for s in db_sources if s.get("type") == "database"]
    if not db_only:
        return ""
    lines: list[str] = []
    for src in db_only:
        payload = src.get("payload") or {}
        driver = _sanitize_identifier(str(payload.get("driver", "?")))
        db_name = _sanitize_identifier(str(payload.get("db_name", "?")))
        source_id = src.get("source_id") or src.get("id")
        tables = (payload.get("schema_snapshot") or {}).get("tables") or []
        names = [
            f"{_sanitize_identifier(str(t.get('schema', '?')))}."
            f"{_sanitize_identifier(str(t.get('name', '?')))}"
            for t in tables
        ]
        table_str = ", ".join(names) if names else "(no introspected tables)"
        lines.append(f"- `{source_id}` ({driver}, db={db_name}): {table_str}")
    return (
        "SQL databases available (for live data — counts, lookups, "
        "aggregations):\n" + "\n".join(lines)
    )


def build_routing_context(
    *,
    kb_names: list[str],
    doc_source_labels: list[str],
    db_sources: list[dict[str, Any]],
) -> str:
    parts: list[str] = []
    if kb_names:
        parts.append("Knowledge bases: " + ", ".join(kb_names))
    if doc_source_labels:
        parts.append("Documents: " + ", ".join(doc_source_labels))
    sql_hint = render_sql_routing_hint(db_sources)
    if sql_hint:
        parts.append(sql_hint)
    return "\n".join(parts)
