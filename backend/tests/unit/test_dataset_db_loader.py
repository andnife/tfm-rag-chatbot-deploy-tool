"""Unit tests for dataset_db_loader — entity rows → EvaluationCase."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from tfm_rag.application.evaluation.dataset_db_loader import load_eval_dataset_from_db

KB_ID = uuid4()
DS_ID = uuid4()


def _make_item(question: str, ground_truth: str, scenario: str, *,
               complexity: str = "easy",
               reference_contexts: list | None = None,
               sql_reference: str | None = None,
               source_doc: str | None = None):
    return SimpleNamespace(
        question=question,
        ground_truth=ground_truth,
        scenario=scenario,
        complexity=complexity,
        reference_contexts=reference_contexts,
        sql_reference=sql_reference,
        source_doc=source_doc,
    )


ITEMS = [
    _make_item("What is the return policy?", "30 days.", "doc_only",
               complexity="easy", reference_contexts=["chunk1", "chunk2"],
               source_doc="policy.pdf"),
    _make_item("List all orders.", "SELECT * FROM orders;", "sql_only",
               complexity="medium", sql_reference="SELECT * FROM orders;"),
    _make_item("How many items?", "See table.", "doc_only",
               complexity="hard", reference_contexts=["chunk3"]),
]


@pytest.fixture()
def fake_ds():
    ds = SimpleNamespace(knowledge_base_id=KB_ID)
    repo = AsyncMock()
    repo.get_dataset = AsyncMock(return_value=ds)
    return repo


@pytest.fixture()
def fake_items():
    repo = AsyncMock()
    repo.list_items_by_dataset = AsyncMock(return_value=ITEMS)
    return repo


@pytest.mark.asyncio
async def test_returns_all_cases_and_kb_id(fake_ds, fake_items):
    cases, kb_id = await load_eval_dataset_from_db(
        ds_repo=fake_ds, item_repo=fake_items, dataset_id=DS_ID,
    )

    assert kb_id == KB_ID
    assert len(cases) == 3

    # first item mapped correctly
    c0 = cases[0]
    assert c0.question == "What is the return policy?"
    assert c0.ground_truth == "30 days."
    assert c0.scenario == "doc_only"
    assert c0.metadata["complexity"] == "easy"
    assert c0.metadata["reference_contexts"] == ["chunk1", "chunk2"]
    assert c0.metadata["sql_reference"] is None
    assert c0.metadata["source_doc"] == "policy.pdf"

    # sql_only item has sql_reference
    c1 = cases[1]
    assert c1.scenario == "sql_only"
    assert c1.metadata["sql_reference"] == "SELECT * FROM orders;"


@pytest.mark.asyncio
async def test_scenario_filter_returns_subset(fake_ds, fake_items):
    cases, kb_id = await load_eval_dataset_from_db(
        ds_repo=fake_ds, item_repo=fake_items, dataset_id=DS_ID,
        scenario_filter="sql_only",
    )

    assert kb_id == KB_ID
    assert len(cases) == 1
    assert cases[0].scenario == "sql_only"


@pytest.mark.asyncio
async def test_reference_contexts_defaults_to_empty_list(fake_ds, fake_items):
    """Items with reference_contexts=None should get [] in metadata."""
    cases, _ = await load_eval_dataset_from_db(
        ds_repo=fake_ds, item_repo=fake_items, dataset_id=DS_ID,
    )
    # third item has reference_contexts=["chunk3"], second has None
    c1 = cases[1]  # sql_only — no reference_contexts set
    assert c1.metadata["reference_contexts"] == []
