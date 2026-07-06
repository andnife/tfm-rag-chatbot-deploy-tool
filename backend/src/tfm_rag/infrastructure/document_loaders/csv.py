"""CSV document loader for the OE-2 ingestion pipeline.

Each row becomes its own chunk-eligible line, formatted as
``col_a: val_a | col_b: val_b | ...`` so that downstream embedders
receive enough context per row.
"""
from __future__ import annotations

import asyncio
import csv as _csv
import io


class CsvLoader:
    mime_type: str = "text/csv"

    async def load(self, content: bytes) -> str:
        def _extract() -> str:
            if not content:
                raise ValueError("CSV payload is empty")

            text = content.decode("utf-8-sig", errors="replace")
            reader = _csv.DictReader(io.StringIO(text))
            if reader.fieldnames is None:
                raise ValueError("CSV payload is missing a header row")

            lines: list[str] = []
            for row in reader:
                parts = [f"{key}: {value}" for key, value in row.items() if value is not None]
                if parts:
                    lines.append(" | ".join(parts))

            if not lines:
                raise ValueError("CSV payload contains no data rows")

            return "\n\n".join(lines)

        # csv module is sync — push it off the event loop for consistency.
        return await asyncio.to_thread(_extract)
