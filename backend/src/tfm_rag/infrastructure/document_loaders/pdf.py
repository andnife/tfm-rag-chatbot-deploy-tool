import asyncio
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class PdfLoader:
    mime_type = "application/pdf"

    async def load(self, content: bytes) -> str:
        def _extract() -> str:
            try:
                reader = PdfReader(BytesIO(content))
            except PdfReadError as exc:
                raise ValueError(f"Not a valid PDF: {exc}") from exc
            parts: list[str] = []
            for page in reader.pages:
                parts.append(page.extract_text() or "")
            return "\n\n".join(p for p in parts if p)

        # pypdf is sync — push it off the event loop.
        return await asyncio.to_thread(_extract)
