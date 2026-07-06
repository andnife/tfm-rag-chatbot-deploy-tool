from pathlib import Path

import pytest

from tfm_rag.infrastructure.document_loaders.markdown import MarkdownLoader

FIXTURE = Path(__file__).parent.parent / "fixtures" / "loaders" / "sample.md"


@pytest.mark.asyncio
async def test_markdown_loader_mime_type() -> None:
    assert MarkdownLoader().mime_type == "text/markdown"


@pytest.mark.asyncio
async def test_markdown_loader_strips_syntax_but_keeps_text() -> None:
    content = FIXTURE.read_bytes()
    text = await MarkdownLoader().load(content)
    assert "Product Overview" in text
    assert "three" in text  # bold preserved as plain
    assert "Semantic search" in text
    assert "User identification is out of MVP scope" in text
    # syntax characters that should NOT be in the plain output:
    assert "**" not in text
    assert "> " not in text


@pytest.mark.asyncio
async def test_markdown_loader_separates_blocks_with_double_newline() -> None:
    content = FIXTURE.read_bytes()
    text = await MarkdownLoader().load(content)
    assert "\n\n" in text


@pytest.mark.asyncio
async def test_markdown_loader_rejects_empty_payload() -> None:
    with pytest.raises(ValueError):
        await MarkdownLoader().load(b"")
