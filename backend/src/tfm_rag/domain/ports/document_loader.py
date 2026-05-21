from typing import Protocol


class DocumentLoader(Protocol):
    """Extracts plain text from a single document of one mime type."""

    mime_type: str

    async def load(self, content: bytes) -> str: ...
