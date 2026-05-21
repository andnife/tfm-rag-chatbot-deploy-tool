import pytest

from tfm_rag.infrastructure.document_loaders.txt import TxtLoader


@pytest.mark.asyncio
async def test_txt_loader_decodes_utf8() -> None:
    loader = TxtLoader()
    text = await loader.load("hola, mundo — ÿ".encode())
    assert text == "hola, mundo — ÿ"


@pytest.mark.asyncio
async def test_txt_loader_handles_crlf() -> None:
    loader = TxtLoader()
    text = await loader.load(b"line1\r\nline2\r\n")
    assert "line1" in text
    assert "line2" in text


@pytest.mark.asyncio
async def test_txt_loader_falls_back_to_latin1_on_bad_utf8() -> None:
    loader = TxtLoader()
    # Pure latin-1 bytes that would raise as utf-8
    text = await loader.load(b"caf\xe9")
    assert "café" in text
