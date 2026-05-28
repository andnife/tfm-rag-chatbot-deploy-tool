"""Compose the agent's system prompt.

The chatbot's user-supplied `system_prompt` is the base; when DB sources
are attached to the chatbot's KBs we append a markdown block listing
each source's tables/columns + its source_id, so the LLM has enough
context to author SELECT queries via the `query_database` tool.
"""
import re
from typing import Any


def _sanitize_identifier(value: str) -> str:
    """Strip characters that could break out of the markdown block or
    inject adversarial content into the system prompt.
    """
    # Remove backticks, quotes, semicolons, and newlines.
    return re.sub(r"[`'\";\n\r]", "", value)


def build_chatbot_system_prompt(
    base_prompt: str, *, db_sources: list[dict[str, Any]] | None = None,
) -> str:
    """Return the final system prompt.

    `db_sources` is the list of Source-shaped dicts; only items with
    `type == 'database'` contribute to the SQL block. The shape is what
    SourcesRepository or the in-router loader produces — `payload` must
    contain `driver`, `db_name`, and `schema_snapshot.tables`.
    """
    if not db_sources:
        return base_prompt
    db_only = [s for s in db_sources if s.get("type") == "database"]
    if not db_only:
        return base_prompt

    blocks: list[str] = []
    for src in db_only:
        payload = src.get("payload") or {}
        driver = _sanitize_identifier(str(payload.get("driver", "?")))
        db_name = _sanitize_identifier(str(payload.get("db_name", "?")))
        source_id = src.get("source_id") or src.get("id")
        snapshot = (payload.get("schema_snapshot") or {})
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
        block = (
            f"Database source `{source_id}` ({driver}, db_name={db_name}):\n"
            + "\n".join(table_lines)
        )
        blocks.append(block)

    sql_section = (
        "\n\n---\nYou ALSO have access to the following SQL databases via "
        "the `query_database` tool. Use it ONLY for questions that need "
        "live data (counts, lookups, aggregations). Compose READ-ONLY "
        "SELECT statements; the system rejects anything else.\n\n"
        + "\n\n".join(blocks)
    )
    return base_prompt + sql_section
