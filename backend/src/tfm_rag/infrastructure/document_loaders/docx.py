"""DOCX document loader for the OE-2 ingestion pipeline."""
from __future__ import annotations

import asyncio
import io
from zipfile import BadZipFile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError


class DocxLoader:
    """Loads a `.docx` file and returns its paragraphs joined by blank lines."""

    mime_type: str = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    async def load(self, content: bytes) -> str:
        def _extract() -> str:
            try:
                document = Document(io.BytesIO(content))
            except (PackageNotFoundError, BadZipFile) as exc:
                raise ValueError("Payload is not a valid DOCX package") from exc

            paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
            return "\n\n".join(paragraphs)

        # python-docx is sync — push it off the event loop.
        return await asyncio.to_thread(_extract)
