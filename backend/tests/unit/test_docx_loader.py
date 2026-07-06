from pathlib import Path

import pytest

from tfm_rag.infrastructure.document_loaders.docx import DocxLoader

FIXTURE = Path(__file__).parent.parent / "fixtures" / "loaders" / "sample.docx"


@pytest.mark.asyncio
async def test_docx_loader_mime_type() -> None:
    loader = DocxLoader()
    assert loader.mime_type == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


@pytest.mark.asyncio
async def test_docx_loader_extracts_paragraphs_in_order() -> None:
    content = FIXTURE.read_bytes()
    text = await DocxLoader().load(content)
    assert "First paragraph" in text
    assert "Second paragraph" in text
    assert "Third paragraph" in text
    assert text.index("First paragraph") < text.index("Second paragraph")
    assert text.index("Second paragraph") < text.index("Third paragraph")


@pytest.mark.asyncio
async def test_docx_loader_separates_paragraphs_with_double_newline() -> None:
    content = FIXTURE.read_bytes()
    text = await DocxLoader().load(content)
    assert "\n\n" in text


@pytest.mark.asyncio
async def test_docx_loader_rejects_non_docx_bytes() -> None:
    with pytest.raises(ValueError):
        await DocxLoader().load(b"not a docx file")
