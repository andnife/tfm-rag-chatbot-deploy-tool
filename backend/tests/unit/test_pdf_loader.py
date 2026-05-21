from io import BytesIO

import pytest
from pypdf import PdfWriter

from tfm_rag.infrastructure.document_loaders.pdf import PdfLoader


def _make_one_page_pdf(text: str) -> bytes:
    """Build a minimal PDF in memory whose first page contains `text`.

    `pypdf.PdfWriter.add_blank_page` + an explicit text stream avoids
    pulling in reportlab as a test dep.
    """
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    page.merge_page(page)  # noop; ensures Resources dict exists
    # We embed the text via the internal /Contents stream so pypdf can
    # extract it on the way out.
    from pypdf.generic import ContentStream, DecodedStreamObject, NameObject

    content_str = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    stream = DecodedStreamObject()
    stream.set_data(content_str)
    page[NameObject("/Contents")] = stream
    # Provide a default Type1 font so the text op decodes:
    from pypdf.generic import DictionaryObject

    font = DictionaryObject()
    font[NameObject("/Type")] = NameObject("/Font")
    font[NameObject("/Subtype")] = NameObject("/Type1")
    font[NameObject("/BaseFont")] = NameObject("/Helvetica")
    resources = page.get("/Resources")
    if not isinstance(resources, DictionaryObject):
        resources = DictionaryObject()
        page[NameObject("/Resources")] = resources
    fonts = DictionaryObject()
    fonts[NameObject("/F1")] = font
    resources[NameObject("/Font")] = fonts
    _ = ContentStream  # silence "unused import" when pypdf prunes API
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.mark.asyncio
async def test_pdf_loader_extracts_text() -> None:
    loader = PdfLoader()
    pdf_bytes = _make_one_page_pdf("hello-rag-pipeline")
    text = await loader.load(pdf_bytes)
    assert "hello-rag-pipeline" in text


@pytest.mark.asyncio
async def test_pdf_loader_rejects_non_pdf() -> None:
    loader = PdfLoader()
    with pytest.raises(ValueError, match="PDF"):
        await loader.load(b"not a pdf at all")
