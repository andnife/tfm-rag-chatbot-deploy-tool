"""Unit tests for the run_ragas_evaluation orchestrator.

We fake answer_query (no real LLM call), fake the RagasEvaluator (no
real ragas call), and verify the use case wires them together correctly.
"""
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tfm_rag.application.evaluation.run_ragas_evaluation import (
    run_ragas_evaluation,
)
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.evaluation import EvaluationError
from tfm_rag.infrastructure.persistence.repository import RequestContext


def _ctx() -> RequestContext:
    return RequestContext(tenant_id=uuid4(), user_id=uuid4())


def _chatbot_row(tenant_id, name: str = "Bot") -> MagicMock:
    row = MagicMock()
    row.id = uuid4()
    row.tenant_id = tenant_id
    row.name = name
    return row


def _write_dataset(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "ds.jsonl"
    p.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    return p


def _answer_view(answer: str, contexts: list[str]) -> MagicMock:
    av = MagicMock()
    av.content = answer
    av.retrieved_contexts = contexts
    av.citations = []
    av.iterations = []
    av.session_id = uuid4()
    av.message_id = uuid4()
    return av


@pytest.mark.asyncio
async def test_runs_each_case_and_returns_scored_report(
    tmp_path: Path,
) -> None:
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = MagicMock()
    chatbot_repo.get = AsyncMock(return_value=row)

    dataset_path = _write_dataset(tmp_path, [
        {"question": "Q1?", "ground_truth": "GT1", "scenario": "doc_only"},
        {"question": "Q2?", "ground_truth": "GT2", "scenario": "doc_only"},
    ])

    answers = [
        _answer_view("A1", ["ctx1"]),
        _answer_view("A2", ["ctx2"]),
    ]
    call_count = 0

    async def fake_answer_query(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        result = answers[call_count]
        call_count += 1
        return result

    fake_evaluator = MagicMock()
    fake_evaluator.judge_model = "llama3.1"
    fake_evaluator.evaluate = MagicMock(
        return_value=[
            {"faithfulness": 0.8, "answer_relevancy": 0.9,
             "context_precision": 0.8, "context_recall": 0.7},
            {"faithfulness": 0.6, "answer_relevancy": 0.7,
             "context_precision": 0.6, "context_recall": 0.5},
        ]
    )

    report = await run_ragas_evaluation(
        MagicMock(), ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        answer_query=fake_answer_query,
        evaluator=fake_evaluator,
        qdrant=MagicMock(),
        embedder_dispatcher=MagicMock(),
        llm_dispatcher=MagicMock(),
        settings=MagicMock(),
        chatbot_id=row.id,
        dataset_path=dataset_path,
        scenario_filter=None,
    )

    assert report.chatbot_name == "Bot"
    assert report.ragas_judge_model == "llama3.1"
    assert len(report.cases) == 2
    assert report.cases[0].predicted_answer == "A1"
    assert report.cases[0].retrieved_contexts == ["ctx1"]
    assert report.cases[0].scores["faithfulness"] == 0.8
    assert report.summary.num_scored == 2
    assert call_count == 2


@pytest.mark.asyncio
async def test_filters_by_scenario(tmp_path: Path) -> None:
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = MagicMock()
    chatbot_repo.get = AsyncMock(return_value=row)

    dataset_path = _write_dataset(tmp_path, [
        {"question": "doc1", "ground_truth": "gt", "scenario": "doc_only"},
        {"question": "abs1", "ground_truth": "gt", "scenario": "abstain"},
        {"question": "doc2", "ground_truth": "gt", "scenario": "doc_only"},
    ])

    called_questions: list[str] = []

    async def fake_answer_query(*args: Any, **kwargs: Any) -> Any:
        called_questions.append(kwargs["user_message"])
        return _answer_view("a", ["c"])

    fake_evaluator = MagicMock()
    fake_evaluator.judge_model = "llama3.1"
    fake_evaluator.evaluate = MagicMock(return_value=[{}, {}])

    report = await run_ragas_evaluation(
        MagicMock(), ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        answer_query=fake_answer_query,
        evaluator=fake_evaluator,
        qdrant=MagicMock(),
        embedder_dispatcher=MagicMock(),
        llm_dispatcher=MagicMock(),
        settings=MagicMock(),
        chatbot_id=row.id,
        dataset_path=dataset_path,
        scenario_filter="doc_only",
    )
    assert called_questions == ["doc1", "doc2"]
    assert report.scenario_filter == "doc_only"


@pytest.mark.asyncio
async def test_answer_query_failure_marks_case_with_error(
    tmp_path: Path,
) -> None:
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = MagicMock()
    chatbot_repo.get = AsyncMock(return_value=row)
    dataset_path = _write_dataset(tmp_path, [
        {"question": "Q1?", "ground_truth": "gt", "scenario": "doc_only"},
        {"question": "Q2?", "ground_truth": "gt", "scenario": "doc_only"},
    ])

    answers = [_answer_view("good", ["c"]), RuntimeError("LLM exploded")]
    idx = 0

    async def fake_answer_query(*args: Any, **kwargs: Any) -> Any:
        nonlocal idx
        result = answers[idx]
        idx += 1
        if isinstance(result, Exception):
            raise result
        return result

    fake_evaluator = MagicMock()
    fake_evaluator.judge_model = "llama3.1"
    fake_evaluator.evaluate = MagicMock(
        return_value=[
            {"faithfulness": 0.7, "answer_relevancy": 0.8,
             "context_precision": 0.7, "context_recall": 0.6},
            {},
        ]
    )

    report = await run_ragas_evaluation(
        MagicMock(), ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        answer_query=fake_answer_query,
        evaluator=fake_evaluator,
        qdrant=MagicMock(),
        embedder_dispatcher=MagicMock(),
        llm_dispatcher=MagicMock(),
        settings=MagicMock(),
        chatbot_id=row.id,
        dataset_path=dataset_path,
        scenario_filter=None,
    )
    assert report.summary.num_scored == 1
    assert report.summary.num_errors == 1
    assert "LLM exploded" in report.cases[1].error


@pytest.mark.asyncio
async def test_raises_when_chatbot_not_found(tmp_path: Path) -> None:
    ctx = _ctx()
    chatbot_repo = MagicMock()
    chatbot_repo.get = AsyncMock(side_effect=NotFoundError("nope"))

    dataset_path = _write_dataset(tmp_path, [
        {"question": "Q?", "ground_truth": "gt", "scenario": "doc_only"},
    ])

    async def fake_unused(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("should not be called")

    fake_eval = MagicMock()
    fake_eval.judge_model = "llama3.1"

    with pytest.raises(ChatbotNotFoundError):
        await run_ragas_evaluation(
            MagicMock(), ctx,
            chatbot_repo_factory=lambda s, c: chatbot_repo,
            answer_query=fake_unused,
            evaluator=fake_eval,
            qdrant=MagicMock(),
            embedder_dispatcher=MagicMock(),
            llm_dispatcher=MagicMock(),
            settings=MagicMock(),
            chatbot_id=uuid4(),
            dataset_path=dataset_path,
            scenario_filter=None,
        )


@pytest.mark.asyncio
async def test_raises_when_dataset_is_empty_after_filter(
    tmp_path: Path,
) -> None:
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = MagicMock()
    chatbot_repo.get = AsyncMock(return_value=row)

    dataset_path = _write_dataset(tmp_path, [
        {"question": "Q?", "ground_truth": "gt", "scenario": "abstain"},
    ])

    async def fake_unused(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("should not be called")

    fake_eval = MagicMock()
    fake_eval.judge_model = "llama3.1"

    with pytest.raises(EvaluationError, match="empty"):
        await run_ragas_evaluation(
            MagicMock(), ctx,
            chatbot_repo_factory=lambda s, c: chatbot_repo,
            answer_query=fake_unused,
            evaluator=fake_eval,
            qdrant=MagicMock(),
            embedder_dispatcher=MagicMock(),
            llm_dispatcher=MagicMock(),
            settings=MagicMock(),
            chatbot_id=row.id,
            dataset_path=dataset_path,
            scenario_filter="doc_only",
        )
