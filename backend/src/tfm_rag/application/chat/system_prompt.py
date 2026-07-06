"""Render a SQL database schema for the sql_generator's thread.

The full column-level schema is injected ONCE into the system message of the
SQL sub-route's conversational thread — never into the chatbot's persona prompt
nor the answer-synthesis prompt (those don't need it, and repeating it dominated
the per-question token bill). The router gets a much lighter table-name-only hint
(see `routing_context.render_sql_routing_hint`).
"""
import re
from typing import Any


def _sanitize_identifier(value: str) -> str:
    """Strip characters that could break out of the markdown block or
    inject adversarial content into the prompt.
    """
    # Remove backticks, quotes, semicolons, and newlines.
    return re.sub(r"[`'\";\n\r]", "", value)


def render_sql_schema(db_sources: list[dict[str, Any]] | None) -> str:
    """Return the tables/columns block for the SQL thread, or "" when there are
    no database sources.

    `db_sources` is the list of Source-shaped dicts; only items with
    `type == 'database'` contribute. The shape is what SourcesRepository or the
    in-router loader produces — `payload` must contain `driver`, `db_name`, and
    `schema_snapshot.tables`.
    """
    if not db_sources:
        return ""
    db_only = [s for s in db_sources if s.get("type") == "database"]
    if not db_only:
        return ""

    blocks: list[str] = []
    for src in db_only:
        payload = src.get("payload") or {}
        driver = _sanitize_identifier(str(payload.get("driver", "?")))
        db_name = _sanitize_identifier(str(payload.get("db_name", "?")))
        source_id = src.get("source_id") or src.get("id")
        snapshot = payload.get("schema_snapshot") or {}
        tables = snapshot.get("tables") or []
        table_lines: list[str] = []
        for t in tables:
            schema = _sanitize_identifier(str(t.get("schema", "?")))
            name = _sanitize_identifier(str(t.get("name", "?")))
            cols = t.get("columns") or []
            col_parts: list[str] = []
            for c in cols:
                cname = _sanitize_identifier(str(c.get("name", "?")))
                ctype = _sanitize_identifier(str(c.get("data_type", "?")))
                nullable = "" if c.get("nullable") else " NOT NULL"
                col_parts.append(f"{cname} {ctype}{nullable}")
            joined_cols = ", ".join(col_parts) if col_parts else "(no columns)"
            table_lines.append(f"  - {schema}.{name} ({joined_cols})")
        if not table_lines:
            table_lines = ["  - (no introspected tables)"]
        blocks.append(
            f"Database source `{source_id}` ({driver}, db_name={db_name}):\n"
            + "\n".join(table_lines)
        )
    return "\n\n".join(blocks)
