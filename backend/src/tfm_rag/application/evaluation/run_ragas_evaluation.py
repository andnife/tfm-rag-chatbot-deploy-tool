import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from tfm_rag.application.chat.answer_query import (
    AnswerView,
)
from tfm_rag.application.chat.answer_query import (
    answer_query as _real_answer_query,
)
from tfm_rag.application.evaluation.dataset_loader import (
    load_evaluation_dataset,
)
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.evaluation import EvaluationError
from tfm_rag.domain.ports.evaluation import EvaluationJudgePort
from tfm_rag.domain.ports.repositories import ChatbotRepositoryPort
from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase
from tfm_rag.domain.value_objects.evaluation_report import (
    EvaluationReport,
    EvaluationSummary,
)

_log = logging.getLogger(__name__)

AnswerQuery = Callable[..., Awaitable[AnswerView]]


async def run_ragas_evaluation(
    *,
    chatbot_repo: ChatbotRepositoryPort,
    answer_query_deps: Mapping[str, Any],
    answer_query: AnswerQuery = _real_answer_query,
    evaluator: EvaluationJudgePort,
    chatbot_id: UUID,
    dataset_path: Path,
    scenario_filter: str | None,
    progress: Callable[[int, int, str], None] | None = None,
    on_case: Callable[[dict[str, Any], int, int], Awaitable[None]] | None = None,
    on_step: Callable[[int, int, str, dict[str, Any]], Awaitable[None]] | None = None,
    should_cancel: Callable[[], Awaitable[bool]] | None = None,
    router_disabled: bool = False,
    cases: list[EvaluationCase] | None = None,
    kb_ids_override: list[UUID] | None = None,
    execution_scorer: Callable[[EvaluationCase], Awaitable[float | None]] | None = None,
    concurrency: int = 1,
    make_case_deps: Callable[[], AbstractAsyncContextManager[Mapping[str, Any]]]
    | None = None,
    resume_done_indices: set[int] | None = None,
) -> EvaluationReport:
    """Run the RAGAS evaluation pipeline.

    1. Validate the chatbot exists in the tenant.
    2. Load the dataset (with optional scenario filter).
    3. For each case: run ``answer_query(persist=False)`` (using the
       pre-built ``answer_query_deps`` from the composition root) to produce a
       prediction + retrieved_contexts. Errors are caught per-case and stored
       on ``case.error``.
    4. Hand the batch to ``evaluator.evaluate(cases)`` to compute RAGAS
       metrics. Errored cases / no-context cases are skipped by the
       evaluator (it returns ``{}`` for those positions).
    5. Build the EvaluationReport with a Summary aggregating the scores.

    ``progress`` is an optional callback (case_idx, total, status) — the
    CLI uses it to print one line per case to stdout.

    Concurrency & resume (Step 3):

    - ``concurrency`` caps how many cases are generated in flight at once.
      ``concurrency == 1`` (the default) preserves the original strictly
      sequential behaviour — including cooperative cancellation that breaks
      between cases.
    - ``make_case_deps`` is an async-context-manager factory yielding a FRESH
      ``answer_query_deps`` bundle (with its OWN AsyncSession) per case. It is
      REQUIRED when ``concurrency > 1`` because concurrent ``answer_query``
      calls must never share a single AsyncSession (asyncpg raises "another
      operation in progress"). When ``None``, the shared ``answer_query_deps``
      is used (the original single-session path).
    - ``resume_done_indices`` are 0-based case indices already generated (e.g.
      recorded in a prior run's trace); they are skipped here (``answer_query``
      is not called and they are not re-emitted via ``on_case``). Their data is
      expected to already be present on the supplied ``cases`` so Steps 4–5
      still score and report them.
    """
    # --- Step 1: validate chatbot ---
    try:
        chatbot = await chatbot_repo.get_chatbot(chatbot_id)
    except NotFoundError as exc:
        raise ChatbotNotFoundError(str(exc)) from exc

    # --- Step 2: load dataset (or use pre-loaded entity input) ---
    if cases is None:
        cases = load_evaluation_dataset(dataset_path, scenario_filter=scenario_filter)
        if not cases:
            raise EvaluationError(
                f"Dataset is empty after applying scenario_filter="
                f"{scenario_filter!r}"
            )

    started_at = datetime.now(UTC)
    total = len(cases)
    resume_done = resume_done_indices or set()

    async def _run_one(idx: int, case: EvaluationCase) -> None:
        """Generate the prediction for one case, mutating it in place.

        Uses a FRESH deps bundle from ``make_case_deps`` when provided (so
        concurrent cases never share an AsyncSession); otherwise falls back to
        the shared ``answer_query_deps``. Exceptions are caught and recorded on
        ``case.error`` so one failing case can't abort the batch.
        """
        async def _fwd(
            step: str, detail: dict[str, Any], _i: int = idx, _t: int = total
        ) -> None:
            if on_step is not None:
                await on_step(_i + 1, _t, step, detail)

        try:
            if make_case_deps is not None:
                async with make_case_deps() as deps:
                    view = await answer_query(
                        **deps,
                        chatbot_id=chatbot_id,
                        session_id=None,
                        user_message=case.question,
                        persist=False,
                        router_disabled=router_disabled,
                        kb_ids_override=kb_ids_override,
                        on_step=_fwd if on_step is not None else None,
                    )
            else:
                view = await answer_query(
                    **answer_query_deps,
                    chatbot_id=chatbot_id,
                    session_id=None,
                    user_message=case.question,
                    persist=False,
                    router_disabled=router_disabled,
                    kb_ids_override=kb_ids_override,
                    on_step=_fwd if on_step is not None else None,
                )
            case.predicted_answer = view.content
            case.retrieved_contexts = list(view.retrieved_contexts)
            case.citations = [c.to_dict() for c in view.citations]
            case.iterations = [it.to_dict() for it in view.iterations]
            case.total_latency_ms = (
                sum(it["latency_ms"] for it in case.iterations)
                if case.iterations else 0.0
            )
            case.routing_trace = dict(getattr(view, "routing_trace", {}) or {})
            case.prompt_tokens = getattr(view, "prompt_tokens", 0) or 0
            case.completion_tokens = getattr(view, "completion_tokens", 0) or 0
        except Exception as exc:  # noqa: BLE001 — record then continue
            case.error = f"{type(exc).__name__}: {exc}"
            _log.warning(
                "run_ragas_evaluation: case %d/%d failed: %s",
                idx + 1, total, exc,
            )

    async def _emit_case(idx: int, case: EvaluationCase) -> None:
        # Emit the just-answered case for live tracing (question, prediction,
        # agentic iterations). A trace sink failure must not abort the eval.
        if on_case is None:
            return
        try:
            await on_case(case.to_dict(), idx + 1, total)
        except Exception:  # noqa: BLE001 — tracing is best-effort
            _log.warning("run_ragas_evaluation: on_case sink failed", exc_info=True)

    # --- Step 3: run each case ---
    if concurrency <= 1:
        # Sequential path (backward compatible): one shared session, strict
        # ordering, cooperative cancel that breaks between cases.
        for idx, case in enumerate(cases):
            if idx in resume_done:
                continue
            if progress is not None:
                progress(idx + 1, total, f"asking: {case.question[:60]}")
            await _run_one(idx, case)
            await _emit_case(idx, case)
            # Cooperative cancellation: check between cases; break yields a
            # partial (but valid) report from the cases processed so far.
            if should_cancel is not None and await should_cancel():
                break
    else:
        # Concurrent path: up to `concurrency` cases in flight, each with its
        # OWN fresh session via `make_case_deps` (never a shared AsyncSession).
        if make_case_deps is None:
            raise EvaluationError(
                "concurrency > 1 requires make_case_deps: each concurrent case "
                "needs its own AsyncSession — sharing one raises asyncpg "
                "'another operation in progress'"
            )
        sem = asyncio.Semaphore(concurrency)
        cancel_requested = False

        async def _worker(idx: int, case: EvaluationCase) -> None:
            nonlocal cancel_requested
            async with sem:
                # Once cancellation is requested, not-yet-started cases bail out
                # (in-flight ones already past this point finish normally).
                if cancel_requested:
                    return
                if progress is not None:
                    progress(idx + 1, total, f"asking: {case.question[:60]}")
                await _run_one(idx, case)
            # Emit + cancel-check outside the semaphore so the slot frees up for
            # the next case while the best-effort trace sink runs. on_case has
            # no internal await, so cumulative sinks stay race-free.
            await _emit_case(idx, case)
            if should_cancel is not None and await should_cancel():
                cancel_requested = True

        tasks = [
            asyncio.create_task(_worker(idx, case))
            for idx, case in enumerate(cases)
            if idx not in resume_done
        ]
        if tasks:
            await asyncio.gather(*tasks)

    # --- Step 4: RAGAS metrics ---
    # A cancellation requested during Step 3 must also skip the scoring batch:
    # it's a long, expensive judge call that serves no purpose once the run
    # is being discarded (the background wrapper drops the report on cancel).
    cancelled = should_cancel is not None and await should_cancel()
    if not cancelled:
        if progress is not None:
            progress(total, total, "scoring with RAGAS...")
        per_case_scores = evaluator.evaluate(cases)
        for case, scores in zip(cases, per_case_scores, strict=True):
            if scores and case.error is None:
                case.scores = scores

        # Optional per-case execution accuracy (SQL result vs gold rows). The
        # scorer decides applicability (returns None when it doesn't apply,
        # e.g. non-SQL); the metric is aggregated generically by
        # EvaluationSummary.from_cases.
        if execution_scorer is not None:
            for case in cases:
                if case.error is not None:
                    continue
                acc = await execution_scorer(case)
                if acc is not None:
                    case.scores = {**(case.scores or {}), "execution_accuracy": acc}

    # --- Step 5: build report ---
    finished_at = datetime.now(UTC)
    summary = EvaluationSummary.from_cases(cases)
    report = EvaluationReport(
        chatbot_id=chatbot_id,
        chatbot_name=chatbot.name,
        dataset_path=str(dataset_path),
        scenario_filter=scenario_filter,
        run_started_at=started_at,
        run_finished_at=finished_at,
        ragas_judge_model=evaluator.judge_model,
        generator_model=chatbot.llm_selection.model_id,
        cases=cases,
        summary=summary,
    )
    return report
