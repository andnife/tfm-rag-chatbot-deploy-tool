"""Unit tests for the SourceView mapping in get_knowledge_base."""
from unittest.mock import MagicMock
from uuid import uuid4

from tfm_rag.application.knowledge.get_knowledge_base import _src_view


def _row(**overrides: object) -> MagicMock:
    row = MagicMock()
    row.id = uuid4()
    row.kb_id = uuid4()
    row.type = "document"
    row.ingest_status = "done"
    row.payload = {"filename": "report.pdf"}
    row.error = None
    row.description = None
    for k, v in overrides.items():
        setattr(row, k, v)
    return row


def test_src_view_carries_description() -> None:
    """The auto-generated document description is surfaced in the view."""
    row = _row(description="A 2-sentence summary of the document.")
    view = _src_view(row)
    assert view.description == "A 2-sentence summary of the document."


def test_src_view_description_defaults_to_none() -> None:
    """A source without a description maps to None (not an error)."""
    row = _row(description=None)
    view = _src_view(row)
    assert view.description is None
