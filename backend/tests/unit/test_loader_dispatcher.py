import pytest

from tfm_rag.domain.errors.knowledge import UnsupportedSourceTypeError
from tfm_rag.infrastructure.document_loaders.csv import CsvLoader
from tfm_rag.infrastructure.document_loaders.dispatcher import (
    LoaderDispatcher,
)
from tfm_rag.infrastructure.document_loaders.docx import DocxLoader
from tfm_rag.infrastructure.document_loaders.markdown import MarkdownLoader
from tfm_rag.infrastructure.document_loaders.pdf import PdfLoader
from tfm_rag.infrastructure.document_loaders.txt import TxtLoader


@pytest.mark.asyncio
async def test_dispatcher_picks_pdf_for_application_pdf() -> None:
    d = LoaderDispatcher([PdfLoader(), TxtLoader()])
    loader = d.for_mime("application/pdf")
    assert isinstance(loader, PdfLoader)


@pytest.mark.asyncio
async def test_dispatcher_picks_txt_for_text_plain() -> None:
    d = LoaderDispatcher([PdfLoader(), TxtLoader()])
    loader = d.for_mime("text/plain")
    assert isinstance(loader, TxtLoader)


@pytest.mark.asyncio
async def test_dispatcher_raises_for_unknown_mime() -> None:
    d = LoaderDispatcher([PdfLoader(), TxtLoader()])
    with pytest.raises(UnsupportedSourceTypeError):
        d.for_mime("image/png")


@pytest.mark.asyncio
async def test_dispatcher_picks_docx_for_docx_mime() -> None:
    d = LoaderDispatcher([PdfLoader(), TxtLoader(), DocxLoader(), CsvLoader(), MarkdownLoader()])
    loader = d.for_mime(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert isinstance(loader, DocxLoader)


@pytest.mark.asyncio
async def test_dispatcher_picks_csv_for_text_csv() -> None:
    d = LoaderDispatcher([PdfLoader(), TxtLoader(), DocxLoader(), CsvLoader(), MarkdownLoader()])
    loader = d.for_mime("text/csv")
    assert isinstance(loader, CsvLoader)


@pytest.mark.asyncio
async def test_dispatcher_picks_markdown_for_text_markdown() -> None:
    d = LoaderDispatcher([PdfLoader(), TxtLoader(), DocxLoader(), CsvLoader(), MarkdownLoader()])
    loader = d.for_mime("text/markdown")
    assert isinstance(loader, MarkdownLoader)
