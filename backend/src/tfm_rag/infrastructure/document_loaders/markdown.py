"""Markdown document loader for the OE-2 ingestion pipeline.

Strips Markdown syntax and emits block-level plain text so the chunker
can split on the natural double-newline boundaries between headings,
paragraphs, lists, and quotes.
"""
from __future__ import annotations

from markdown_it import MarkdownIt


class MarkdownLoader:
    mime_type: str = "text/markdown"

    def __init__(self) -> None:
        self._md = MarkdownIt("commonmark")

    async def load(self, content: bytes) -> str:
        if not content:
            raise ValueError("Markdown payload is empty")

        text = content.decode("utf-8", errors="replace")
        tokens = self._md.parse(text)

        text_types = {"text", "code_inline", "softbreak"}

        blocks: list[str] = []
        current: list[str] = []
        for token in tokens:
            if token.type == "inline" and token.children:
                parts = [
                    child.content
                    for child in token.children
                    if child.type in text_types
                ]
                current.append("".join(parts))
            elif token.type.endswith("_close") and current:
                blocks.append(" ".join(part.strip() for part in current if part.strip()))
                current = []

        if current:
            blocks.append(" ".join(part.strip() for part in current if part.strip()))

        return "\n\n".join(block for block in blocks if block)
