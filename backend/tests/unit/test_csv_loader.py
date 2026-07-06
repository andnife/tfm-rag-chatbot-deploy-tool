from pathlib import Path

import pytest

from tfm_rag.infrastructure.document_loaders.csv import CsvLoader

FIXTURE = Path(__file__).parent.parent / "fixtures" / "loaders" / "sample.csv"


@pytest.mark.asyncio
async def test_csv_loader_mime_type() -> None:
    assert CsvLoader().mime_type == "text/csv"


@pytest.mark.asyncio
async def test_csv_loader_emits_one_row_per_chunk_with_header_labels() -> None:
    content = FIXTURE.read_bytes()
    text = await CsvLoader().load(content)
    assert "product: Lamp X1 | stock: 12 | price_eur: 29.99" in text
    assert "product: Sofa Y2 | stock: 3 | price_eur: 499.00" in text
    assert "product: Table Z3 | stock: 0 | price_eur: 159.50" in text


@pytest.mark.asyncio
async def test_csv_loader_separates_rows_with_double_newline() -> None:
    content = FIXTURE.read_bytes()
    text = await CsvLoader().load(content)
    assert text.count("\n\n") >= 2


@pytest.mark.asyncio
async def test_csv_loader_rejects_empty_payload() -> None:
    with pytest.raises(ValueError):
        await CsvLoader().load(b"")
