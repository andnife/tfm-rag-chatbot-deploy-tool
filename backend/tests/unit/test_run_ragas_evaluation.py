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
    chatbot_repo.get_chatbot = AsyncMock(return_value=row)

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
        chatbot_repo=chatbot_repo,
        answer_query_deps={},
        answer_query=fake_answer_query,
        evaluator=fake_evaluator,
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
async def test_execution_scorer_adds_execution_accuracy(tmp_path: Path) -> None:
    """When an execution_scorer is provided, its verdict is stored as
    `execution_accuracy` on each non-errored case and surfaces in the summary
    (the proper correctness metric for SQL: generated result vs gold rows)."""
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = MagicMock()
    chatbot_repo.get_chatbot = AsyncMock(return_value=row)
    dataset_path = _write_dataset(tmp_path, [
        {"question": "how many?", "ground_truth": "3", "scenario": "sql_only",
         "sql_reference": "SELECT COUNT(*) FROM t"},
    ])

    async def fake_answer_query(*args: Any, **kwargs: Any) -> Any:
        return _answer_view("There are 3.", ["SQL query:\nSELECT ...\nResult:\n| c |\n| 3 |"])

    fake_evaluator = MagicMock()
    fake_evaluator.judge_model = "j"
    fake_evaluator.evaluate = MagicMock(return_value=[{"faithfulness": 0.5}])

    async def scorer(case: Any) -> float:
        return 1.0

    report = await run_ragas_evaluation(
        chatbot_repo=chatbot_repo, answer_query_deps={},
        answer_query=fake_answer_query, evaluator=fake_evaluator,
        chatbot_id=row.id, dataset_path=dataset_path, scenario_filter=None,
        execution_scorer=scorer,
    )
    assert report.cases[0].scores["execution_accuracy"] == 1.0
    assert "execution_accuracy" in report.summary.metrics


@pytest.mark.asyncio
async def test_filters_by_scenario(tmp_path: Path) -> None:
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = MagicMock()
    chatbot_repo.get_chatbot = AsyncMock(return_value=row)

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
        chatbot_repo=chatbot_repo,
        answer_query_deps={},
        answer_query=fake_answer_query,
        evaluator=fake_evaluator,
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
    chatbot_repo.get_chatbot = AsyncMock(return_value=row)
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
        chatbot_repo=chatbot_repo,
        answer_query_deps={},
        answer_query=fake_answer_query,
        evaluator=fake_evaluator,
        chatbot_id=row.id,
        dataset_path=dataset_path,
        scenario_filter=None,
    )
    assert report.summary.num_scored == 1
    assert report.summary.num_errors == 1
    assert "LLM exploded" in report.cases[1].error


@pytest.mark.asyncio
async def test_raises_when_chatbot_not_found(tmp_path: Path) -> None:
    chatbot_repo = MagicMock()
    chatbot_repo.get_chatbot = AsyncMock(side_effect=NotFoundError("nope"))

    dataset_path = _write_dataset(tmp_path, [
        {"question": "Q?", "ground_truth": "gt", "scenario": "doc_only"},
    ])

    async def fake_unused(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("should not be called")

    fake_eval = MagicMock()
    fake_eval.judge_model = "llama3.1"

    with pytest.raises(ChatbotNotFoundError):
        await run_ragas_evaluation(
            chatbot_repo=chatbot_repo,
            answer_query_deps={},
            answer_query=fake_unused,
            evaluator=fake_eval,
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
    chatbot_repo.get_chatbot = AsyncMock(return_value=row)

    dataset_path = _write_dataset(tmp_path, [
        {"question": "Q?", "ground_truth": "gt", "scenario": "abstain"},
    ])

    async def fake_unused(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("should not be called")

    fake_eval = MagicMock()
    fake_eval.judge_model = "llama3.1"

    with pytest.raises(EvaluationError, match="empty"):
        await run_ragas_evaluation(
            chatbot_repo=chatbot_repo,
            answer_query_deps={},
            answer_query=fake_unused,
            evaluator=fake_eval,
            chatbot_id=row.id,
            dataset_path=dataset_path,
            scenario_filter="doc_only",
        )


@pytest.mark.asyncio
async def test_captures_routing_trace_per_case(tmp_path: Path) -> None:
    row = MagicMock()
    row.name = "Bot"
    chatbot_repo = MagicMock()
    chatbot_repo.get_chatbot = AsyncMock(return_value=row)

    dataset_path = tmp_path / "ds.jsonl"
    dataset_path.write_text(
        json.dumps({"question": "Q1?", "ground_truth": "GT1", "scenario": "doc_only"}) + "\n",
        encoding="utf-8",
    )

    view = MagicMock(
        content="A1", retrieved_contexts=["ctx1"], citations=[], iterations=[],
        session_id=uuid4(), message_id=uuid4(),
        routing_trace={"route": "docs", "rationale": "f", "attempts": [], "verdicts": []},
    )

    async def fake_answer_query(*a, **k):
        return view

    fake_evaluator = MagicMock()
    fake_evaluator.judge_model = "x"
    fake_evaluator.evaluate = MagicMock(return_value=[{"faithfulness": 0.8}])

    report = await run_ragas_evaluation(
        chatbot_repo=chatbot_repo,
        answer_query_deps={},
        answer_query=fake_answer_query, evaluator=fake_evaluator,
        chatbot_id=uuid4(), dataset_path=dataset_path, scenario_filter=None,
    )
    assert report.cases[0].routing_trace["route"] == "docs"


@pytest.mark.asyncio
async def test_entity_input_cases_skip_file_loader(tmp_path: Path) -> None:
    """When `cases` is supplied, the file loader is skipped entirely."""
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = MagicMock()
    chatbot_repo.get_chatbot = AsyncMock(return_value=row)

    from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase

    injected = [
        EvaluationCase(question="Q1?", ground_truth="GT1", scenario="doc_only"),
    ]

    av = MagicMock()
    av.content = "A1"
    av.retrieved_contexts = ["ctx1"]
    av.citations = []
    av.iterations = []
    av.prompt_tokens = 10
    av.completion_tokens = 4

    async def fake_answer_query(*args: Any, **kwargs: Any) -> Any:
        return av

    fake_evaluator = MagicMock()
    fake_evaluator.judge_model = "llama3.1"
    fake_evaluator.evaluate = MagicMock(return_value=[{"faithfulness": 0.9}])

    # dataset_path points to a non-existent file — proves file loader is skipped
    report = await run_ragas_evaluation(
        chatbot_repo=chatbot_repo,
        answer_query_deps={},
        answer_query=fake_answer_query,
        evaluator=fake_evaluator,
        chatbot_id=row.id,
        dataset_path=tmp_path / "nonexistent.jsonl",
        scenario_filter=None,
        cases=injected,
    )

    assert len(report.cases) == 1
    assert report.cases[0].predicted_answer == "A1"


@pytest.mark.asyncio
async def test_entity_input_captures_per_case_tokens(tmp_path: Path) -> None:
    """Token fields are transferred from AnswerView to EvaluationCase."""
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = MagicMock()
    chatbot_repo.get_chatbot = AsyncMock(return_value=row)

    from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase

    injected = [
        EvaluationCase(question="Q1?", ground_truth="GT1", scenario="doc_only"),
        EvaluationCase(question="Q2?", ground_truth="GT2", scenario="doc_only"),
    ]

    call_count = 0

    async def fake_answer_query(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        av = MagicMock()
        av.content = f"A{call_count + 1}"
        av.retrieved_contexts = [f"ctx{call_count + 1}"]
        av.citations = []
        av.iterations = []
        av.prompt_tokens = 10
        av.completion_tokens = 4
        call_count += 1
        return av

    fake_evaluator = MagicMock()
    fake_evaluator.judge_model = "llama3.1"
    fake_evaluator.evaluate = MagicMock(
        return_value=[{"faithfulness": 0.9}, {"faithfulness": 0.8}]
    )

    report = await run_ragas_evaluation(
        chatbot_repo=chatbot_repo,
        answer_query_deps={},
        answer_query=fake_answer_query,
        evaluator=fake_evaluator,
        chatbot_id=row.id,
        dataset_path=tmp_path / "nonexistent.jsonl",
        scenario_filter=None,
        cases=injected,
    )

    # Per-case token capture
    assert report.cases[0].prompt_tokens == 10
    assert report.cases[0].completion_tokens == 4
    assert report.cases[1].prompt_tokens == 10
    assert report.cases[1].completion_tokens == 4

    # Summary token totals (2 cases × 10/4)
    summary_data = report.summary.to_dict()
    assert summary_data["tokens"]["gen_prompt"] == 20
    assert summary_data["tokens"]["gen_completion"] == 8


@pytest.mark.asyncio
async def test_kb_ids_override_forwarded_to_answer_query(tmp_path: Path) -> None:
    """kb_ids_override is passed through to every answer_query call."""
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = MagicMock()
    chatbot_repo.get_chatbot = AsyncMock(return_value=row)

    from uuid import uuid4 as _uuid4

    from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase

    kb_ids = [_uuid4(), _uuid4()]
    seen_overrides: list[Any] = []

    async def fake_answer_query(*args: Any, **kwargs: Any) -> Any:
        seen_overrides.append(kwargs.get("kb_ids_override"))
        av = MagicMock()
        av.content = "A"
        av.retrieved_contexts = ["c"]
        av.citations = []
        av.iterations = []
        av.prompt_tokens = 5
        av.completion_tokens = 2
        return av

    injected = [
        EvaluationCase(question="Q?", ground_truth="GT", scenario="doc_only"),
    ]

    fake_evaluator = MagicMock()
    fake_evaluator.judge_model = "llama3.1"
    fake_evaluator.evaluate = MagicMock(return_value=[{"faithfulness": 0.9}])

    await run_ragas_evaluation(
        chatbot_repo=chatbot_repo,
        answer_query_deps={},
        answer_query=fake_answer_query,
        evaluator=fake_evaluator,
        chatbot_id=row.id,
        dataset_path=tmp_path / "nonexistent.jsonl",
        scenario_filter=None,
        cases=injected,
        kb_ids_override=kb_ids,
    )

    assert len(seen_overrides) == 1
    assert seen_overrides[0] == kb_ids


@pytest.mark.asyncio
async def test_case_total_latency_is_sum_of_iterations(tmp_path: Path) -> None:
    """total_latency_ms on each case equals the sum of its iteration latency_ms values."""
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = MagicMock()
    chatbot_repo.get_chatbot = AsyncMock(return_value=row)

    from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase

    injected = [
        EvaluationCase(question="Q1?", ground_truth="GT1", scenario="doc_only"),
        EvaluationCase(question="Q2?", ground_truth="GT2", scenario="doc_only"),
    ]

    # Build fake iterations with known latency_ms values
    def _fake_iter(latency: float) -> MagicMock:
        it = MagicMock()
        it.to_dict.return_value = {"latency_ms": latency, "tool": "retrieve"}
        return it

    answers = [
        # case 0: two iterations totalling 300 ms
        MagicMock(
            content="A1", retrieved_contexts=["ctx1"], citations=[],
            iterations=[_fake_iter(100.0), _fake_iter(200.0)],
            prompt_tokens=10, completion_tokens=4,
        ),
        # case 1: no iterations (total should be 0.0)
        MagicMock(
            content="A2", retrieved_contexts=["ctx2"], citations=[],
            iterations=[],
            prompt_tokens=5, completion_tokens=2,
        ),
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
        return_value=[{"faithfulness": 0.9}, {"faithfulness": 0.8}]
    )

    report = await run_ragas_evaluation(
        chatbot_repo=chatbot_repo,
        answer_query_deps={},
        answer_query=fake_answer_query,
        evaluator=fake_evaluator,
        chatbot_id=row.id,
        dataset_path=tmp_path / "nonexistent.jsonl",
        scenario_filter=None,
        cases=injected,
    )

    case0 = report.cases[0]
    case1 = report.cases[1]

    # case 0: sum of [100.0, 200.0] = 300.0
    expected0 = sum(it["latency_ms"] for it in case0.iterations)
    assert case0.total_latency_ms == expected0
    assert "total_latency_ms" in case0.to_dict()

    # case 1: no iterations → 0.0
    assert case1.total_latency_ms == 0.0
    assert "total_latency_ms" in case1.to_dict()


@pytest.mark.asyncio
async def test_forwards_router_disabled_to_answer_query(tmp_path: Path) -> None:
    row = MagicMock()
    row.name = "Bot"
    chatbot_repo = MagicMock()
    chatbot_repo.get_chatbot = AsyncMock(return_value=row)
    dataset_path = tmp_path / "ds.jsonl"
    dataset_path.write_text(
        json.dumps({"question": "Q?", "ground_truth": "GT", "scenario": "mixed"}) + "\n",
        encoding="utf-8",
    )
    seen: dict = {}

    async def fake_answer_query(*a, **k):
        seen["router_disabled"] = k.get("router_disabled")
        return MagicMock(content="A", retrieved_contexts=["c"], citations=[],
                         iterations=[], routing_trace={"route": "docs"},
                         session_id=uuid4(), message_id=uuid4())

    fake_eval = MagicMock()
    fake_eval.judge_model = "x"
    fake_eval.evaluate = MagicMock(return_value=[{"faithfulness": 0.8}])

    await run_ragas_evaluation(
        chatbot_repo=chatbot_repo,
        answer_query_deps={},
        answer_query=fake_answer_query,
        evaluator=fake_eval,
        chatbot_id=uuid4(),
        dataset_path=dataset_path,
        scenario_filter=None,
        router_disabled=True,
    )
    assert seen["router_disabled"] is True


@pytest.mark.asyncio
async def test_on_step_receives_events_tagged_with_case_index(tmp_path: Path) -> None:
    """on_step is called with (case_idx, total, step, detail) for each case."""
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = MagicMock()
    chatbot_repo.get_chatbot = AsyncMock(return_value=row)

    from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase

    injected = [
        EvaluationCase(question="Q1?", ground_truth="GT1", scenario="doc_only"),
        EvaluationCase(question="Q2?", ground_truth="GT2", scenario="doc_only"),
    ]

    received_events: list[tuple] = []

    async def fake_on_step(case_idx: int, total: int, step: str, detail: dict) -> None:
        received_events.append((case_idx, total, step, detail))

    async def fake_answer_query(*args: Any, **kwargs: Any) -> Any:
        # Invoke the on_step callback if provided (simulates Task 2 behaviour)
        on_step = kwargs.get("on_step")
        if on_step is not None:
            await on_step("retrieve", {"docs": 3})
        av = MagicMock()
        av.content = "A"
        av.retrieved_contexts = ["c"]
        av.citations = []
        av.iterations = []
        av.prompt_tokens = 5
        av.completion_tokens = 2
        return av

    fake_evaluator = MagicMock()
    fake_evaluator.judge_model = "llama3.1"
    fake_evaluator.evaluate = MagicMock(
        return_value=[{"faithfulness": 0.9}, {"faithfulness": 0.8}]
    )

    await run_ragas_evaluation(
        chatbot_repo=chatbot_repo,
        answer_query_deps={},
        answer_query=fake_answer_query,
        evaluator=fake_evaluator,
        chatbot_id=row.id,
        dataset_path=tmp_path / "nonexistent.jsonl",
        scenario_filter=None,
        cases=injected,
        on_step=fake_on_step,
    )

    # Two cases → two events, each tagged with the correct 1-based case index and total
    assert len(received_events) == 2
    assert received_events[0] == (1, 2, "retrieve", {"docs": 3})
    assert received_events[1] == (2, 2, "retrieve", {"docs": 3})


@pytest.mark.asyncio
async def test_should_cancel_breaks_loop_after_first_case(tmp_path: Path) -> None:
    """When should_cancel returns True after case 1, only 1 case is processed."""
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = MagicMock()
    chatbot_repo.get_chatbot = AsyncMock(return_value=row)

    from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase

    injected = [
        EvaluationCase(question="Q1?", ground_truth="GT1", scenario="doc_only"),
        EvaluationCase(question="Q2?", ground_truth="GT2", scenario="doc_only"),
        EvaluationCase(question="Q3?", ground_truth="GT3", scenario="doc_only"),
    ]

    call_count = 0

    async def fake_answer_query(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        av = MagicMock()
        av.content = f"A{call_count}"
        av.retrieved_contexts = ["c"]
        av.citations = []
        av.iterations = []
        av.prompt_tokens = 5
        av.completion_tokens = 2
        return av

    cancel_calls = 0

    async def should_cancel() -> bool:
        nonlocal cancel_calls
        cancel_calls += 1
        # Cancel after the first case
        return cancel_calls >= 1

    fake_evaluator = MagicMock()
    fake_evaluator.judge_model = "llama3.1"
    # evaluator receives all 3 cases (same length as injected), returns {} for unanswered ones
    fake_evaluator.evaluate = MagicMock(return_value=[{"faithfulness": 0.9}, {}, {}])

    report = await run_ragas_evaluation(
        chatbot_repo=chatbot_repo,
        answer_query_deps={},
        answer_query=fake_answer_query,
        evaluator=fake_evaluator,
        chatbot_id=row.id,
        dataset_path=tmp_path / "nonexistent.jsonl",
        scenario_filter=None,
        cases=injected,
        should_cancel=should_cancel,
    )

    # Only 1 answer_query call made (loop broke after case 0)
    assert call_count == 1
    # Report is valid (partial) — all 3 cases in list, only first has a predicted_answer
    assert len(report.cases) == 3
    assert report.cases[0].predicted_answer == "A1"
    assert report.cases[1].predicted_answer is None
    assert report.cases[2].predicted_answer is None


@pytest.mark.asyncio
async def test_should_cancel_skips_ragas_scoring_batch(tmp_path: Path) -> None:
    """When cancellation is requested, the (expensive) RAGAS scoring batch —
    and the execution_scorer loop — must not run at all; a partial, unscored
    report is still returned."""
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = MagicMock()
    chatbot_repo.get_chatbot = AsyncMock(return_value=row)

    from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase

    injected = [
        EvaluationCase(question="Q1?", ground_truth="GT1", scenario="doc_only"),
        EvaluationCase(question="Q2?", ground_truth="GT2", scenario="doc_only"),
    ]

    async def fake_answer_query(*args: Any, **kwargs: Any) -> Any:
        return _answer_view("A", ["c"])

    async def should_cancel() -> bool:
        return True

    fake_evaluator = MagicMock()
    fake_evaluator.judge_model = "llama3.1"
    fake_evaluator.evaluate = MagicMock(return_value=[{"faithfulness": 0.9}, {}])

    execution_scorer = AsyncMock(return_value=1.0)

    report = await run_ragas_evaluation(
        chatbot_repo=chatbot_repo,
        answer_query_deps={},
        answer_query=fake_answer_query,
        evaluator=fake_evaluator,
        chatbot_id=row.id,
        dataset_path=tmp_path / "nonexistent.jsonl",
        scenario_filter=None,
        cases=injected,
        should_cancel=should_cancel,
        execution_scorer=execution_scorer,
    )

    fake_evaluator.evaluate.assert_not_called()
    execution_scorer.assert_not_called()
    assert len(report.cases) == 2
    assert not report.cases[0].scores
