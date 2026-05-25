"""SqlQueryResult — single read-only query result returned by a
DatabaseConnector.run_select call.

Persisted shape (when included in RetrievalIteration metadata) is what
to_dict() emits. Rows are JSON-safe (UUID/datetime are stringified
by the connector before reaching this VO).
"""
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SqlQueryResult:
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    truncated: bool

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": list(self.columns),
            "rows": [dict(r) for r in self.rows],
            "truncated": self.truncated,
            "row_count": self.row_count,
        }

    def to_markdown(self) -> str:
        """Render as a small markdown table for inclusion in the tool
        response message back to the LLM. Truncated at 20 rows in display
        even if `rows` holds more (keeps the LLM context bounded)."""
        if not self.columns:
            return "(no columns)"
        if not self.rows:
            return f"| {' | '.join(self.columns)} |\n|{'|'.join(['---'] * len(self.columns))}|\n(0 rows)"
        DISPLAY_CAP = 20
        head = f"| {' | '.join(self.columns)} |"
        sep = f"|{'|'.join(['---'] * len(self.columns))}|"
        body_rows = self.rows[:DISPLAY_CAP]
        lines = [head, sep]
        for r in body_rows:
            lines.append(
                "| " + " | ".join(str(r.get(c, "")) for c in self.columns) + " |"
            )
        suffix = ""
        if len(self.rows) > DISPLAY_CAP:
            suffix = f"\n(showing {DISPLAY_CAP} of {len(self.rows)} rows)"
        if self.truncated:
            suffix += "\n(result was truncated by the server limit)"
        return "\n".join(lines) + suffix
