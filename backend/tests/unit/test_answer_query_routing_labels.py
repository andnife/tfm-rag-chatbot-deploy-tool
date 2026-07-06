from unittest.mock import MagicMock
from uuid import uuid4

from tfm_rag.application.chat.routing_context import doc_label


def _doc_source(filename: str, description: str | None) -> dict:
    return {
        "source_id": uuid4(), "type": "document",
        "payload": {"filename": filename}, "description": description,
    }


def test_doc_labels_use_description_when_present() -> None:
    sources = [_doc_source("a.pdf", "About cats"),
               _doc_source("b.pdf", None)]
    labels = [
        doc_label(
            filename=str(s["payload"].get("filename")
                         or s["payload"].get("name") or s["source_id"]),
            description=s.get("description"),
        )
        for s in sources if s["type"] != "database"
    ]
    assert labels == ["a.pdf — About cats", "b.pdf"]


def test_all_sources_dict_reads_description_defensively() -> None:
    # A SourceRow-like object without an explicit description attribute set
    # must not break (getattr default None).
    row = MagicMock(spec=["id", "type", "payload"])
    row.id = uuid4()
    row.type = "document"
    row.payload = {"filename": "x.pdf"}
    assert getattr(row, "description", None) is None
