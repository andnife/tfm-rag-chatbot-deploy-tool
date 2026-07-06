"""Unit tests for CONCURRENT + RESUMABLE generation in run_ragas_evaluation.

Everything here is mocked — no DB, no models, no network:
  - ``answer_query`` is a fake coroutine that records the max number of
    simultaneous in-flight calls and can raise on demand,
  - ``make_case_deps`` is a fake async-context-manager factory that yields a
    UNIQUE sentinel deps bundle per call (so we can prove concurrent cases never
    share one AsyncSession).
"""
import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tfm_rag.domain.errors.evaluation import EvaluationError
from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase


def _chatbot_repo() -> MagicMock:
    row = MagicMock()
    row.id = uuid4()
    row.name = "Bot"
    row.llm_selection.model_id = "gen-model"
    repo = MagicMock()
    repo.get_chatbot = AsyncMock(return_value=row)
    return repo


def _cases(n: int) -> list[EvaluationCase]:
    return [
        EvaluationCase(question=f"Q{i}", ground_truth=f"G{i}", scenario="doc_only")
        for i in range(n)
    ]


def _evaluator() -> MagicMock:
    ev = MagicMock()
    ev.judge_model = "judge"
    ev.evaluate = MagicMock(side_effect=lambda cs: [{"faithfulness": 0.9} for _ in cs])
    return ev


def _view(content: str) -> MagicMock:
    av = MagicMock()
    av.content = content
    av.retrieved_contexts = ["c"]
    av.citations = []
    av.iterations = []
    av.routing_trace = {}
    av.prompt_tokens = 1
    av.completion_tokens = 1
    return av


async def _run(**kwargs: Any) -> Any:
    # Imported here so a collection-time import error surfaces per-test.
    from tfm_rag.application.evaluation.run_ragas_evaluation import (
        run_ragas_evaluation,
    )

    return await run_ragas_evaluation(
        chatbot_repo=_chatbot_repo(),
        evaluator=_evaluator(),
        chatbot_id=uuid4(),
        dataset_path=Path("entity:test"),
        scenario_filter=None,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_concurrency_caps_inflight_and_uses_distinct_deps() -> None:
    """concurrency=3 over 6 cases: never more than 3 answer_query calls in
    flight at once, and each case gets its OWN deps object (no shared session)."""
    cases = _cases(6)
    concurrency = 3

    in_flight = 0
    max_in_flight = 0
    gate = asyncio.Event()

    made_deps: list[object] = []
    seen_deps: list[object] = []

    @asynccontextmanager
    async def make_case_deps() -> AsyncIterator[Mapping[str, Any]]:
        sentinel = object()
        made_deps.append(sentinel)
        yield {"_deps_id": sentinel}

    async def fake_answer_query(**kwargs: Any) -> Any:
        nonlocal in_flight, max_in_flight
        seen_deps.append(kwargs["_deps_id"])
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        # Once `concurrency` calls have piled up, release everyone; the semaphore
        # (not this gate) is what keeps the ceiling at `concurrency`.
        if in_flight >= concurrency:
            gate.set()
        await gate.wait()
        in_flight -= 1
        return _view(f"ans:{kwargs['user_message']}")

    report = await _run(
        answer_query_deps={},
        answer_query=fake_answer_query,
        cases=cases,
        concurrency=concurrency,
        make_case_deps=make_case_deps,
    )

    assert max_in_flight == concurrency
    # One distinct deps bundle created and used per case (no shared session).
    assert len(made_deps) == 6
    assert len({id(d) for d in seen_deps}) == 6
    assert set(seen_deps) == set(made_deps)
    # Results correctly associated by idx despite out-of-order completion.
    for c in report.cases:
        assert c.predicted_answer == f"ans:{c.question}"


@pytest.mark.asyncio
async def test_resume_skips_done_indices() -> None:
    """resume_done_indices are never handed to answer_query and are not
    re-emitted via on_case; only the remaining cases are generated."""
    cases = _cases(4)
    # Pretend 0 and 2 were already generated in a prior attempt.
    cases[0].predicted_answer = "old0"
    cases[2].predicted_answer = "old2"

    asked: list[str] = []
    emitted: list[int] = []

    @asynccontextmanager
    async def make_case_deps() -> AsyncIterator[Mapping[str, Any]]:
        yield {"_deps_id": object()}

    async def fake_answer_query(**kwargs: Any) -> Any:
        asked.append(kwargs["user_message"])
        return _view(f"new:{kwargs['user_message']}")

    async def on_case(case: dict[str, Any], idx: int, total: int) -> None:
        emitted.append(idx - 1)  # store 0-based

    report = await _run(
        answer_query_deps={},
        answer_query=fake_answer_query,
        cases=cases,
        concurrency=2,
        make_case_deps=make_case_deps,
        resume_done_indices={0, 2},
        on_case=on_case,
    )

    assert sorted(asked) == ["Q1", "Q3"]
    assert sorted(emitted) == [1, 3]
    # Resumed cases keep their pre-loaded data; regenerated ones are fresh.
    assert report.cases[0].predicted_answer == "old0"
    assert report.cases[1].predicted_answer == "new:Q1"
    assert report.cases[2].predicted_answer == "old2"
    assert report.cases[3].predicted_answer == "new:Q3"


@pytest.mark.asyncio
async def test_one_failing_case_does_not_abort_the_others() -> None:
    """A case whose answer_query raises records case.error; the rest still run
    and stay correctly associated by idx."""
    cases = _cases(4)

    @asynccontextmanager
    async def make_case_deps() -> AsyncIterator[Mapping[str, Any]]:
        yield {"_deps_id": object()}

    async def fake_answer_query(**kwargs: Any) -> Any:
        if kwargs["user_message"] == "Q2":
            raise RuntimeError("boom on Q2")
        return _view(f"ans:{kwargs['user_message']}")

    report = await _run(
        answer_query_deps={},
        answer_query=fake_answer_query,
        cases=cases,
        concurrency=3,
        make_case_deps=make_case_deps,
    )

    assert report.cases[0].predicted_answer == "ans:Q0"
    assert report.cases[1].predicted_answer == "ans:Q1"
    assert report.cases[2].predicted_answer is None
    assert report.cases[2].error is not None
    assert "boom on Q2" in report.cases[2].error
    assert report.cases[3].predicted_answer == "ans:Q3"


@pytest.mark.asyncio
async def test_concurrency_gt_1_requires_make_case_deps() -> None:
    """concurrency > 1 without a per-case factory is a misconfiguration —
    sharing one session would raise asyncpg 'another operation in progress'."""

    async def fake_answer_query(**kwargs: Any) -> Any:
        return _view("x")

    with pytest.raises(EvaluationError, match="make_case_deps"):
        await _run(
            answer_query_deps={},
            answer_query=fake_answer_query,
            cases=_cases(2),
            concurrency=2,
            make_case_deps=None,
        )


@pytest.mark.asyncio
async def test_concurrency_1_uses_shared_deps_backward_compat() -> None:
    """concurrency==1 with make_case_deps=None keeps the original single-session
    path: every call reuses the one shared answer_query_deps bundle."""
    shared = object()
    seen: list[object] = []
    make_calls = 0

    @asynccontextmanager
    async def make_case_deps() -> AsyncIterator[Mapping[str, Any]]:
        nonlocal make_calls
        make_calls += 1
        yield {"_deps_id": object()}

    async def fake_answer_query(**kwargs: Any) -> Any:
        seen.append(kwargs["_deps_id"])
        return _view(f"ans:{kwargs['user_message']}")

    report = await _run(
        answer_query_deps={"_deps_id": shared},
        answer_query=fake_answer_query,
        cases=_cases(3),
        concurrency=1,
        make_case_deps=None,
    )

    assert make_calls == 0
    assert seen == [shared, shared, shared]
    for c in report.cases:
        assert c.predicted_answer == f"ans:{c.question}"
