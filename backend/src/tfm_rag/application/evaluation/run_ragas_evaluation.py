import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

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
from tfm_rag.domain.value_objects.evaluation_report import (
    EvaluationReport,
    EvaluationSummary,
)
from tfm_rag.infrastructure.embedders.dispatcher import EmbedderDispatcher
from tfm_rag.infrastructure.evaluation.ragas_evaluator import RagasEvaluator
from tfm_rag.infrastructure.llm_providers.dispatcher import LLMDispatcher
from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
    ChatbotRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.settings import Settings
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore

_log = logging.getLogger(__name__)

ChatbotRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatbotRepository
]
AnswerQuery = Callable[..., Awaitable[AnswerView]]


def _default_chatbot_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatbotRepository:
    return ChatbotRepository(session, ctx)


async def run_ragas_evaluation(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    chatbot_repo_factory: ChatbotRepoFactory = _default_chatbot_repo,
    answer_query: AnswerQuery = _real_answer_query,
    evaluator: RagasEvaluator,
    qdrant: QdrantStore,
    embedder_dispatcher: EmbedderDispatcher,
    llm_dispatcher: LLMDispatcher,
    settings: Settings,
    chatbot_id: UUID,
    dataset_path: Path,
    scenario_filter: str | None,
    progress: Callable[[int, int, str], None] | None = None,
) -> EvaluationReport:
    """Run the RAGAS evaluation pipeline.

    1. Validate the chatbot exists in the tenant.
    2. Load the dataset (with optional scenario filter).
    3. For each case: run ``answer_query(persist=False)`` to produce a
       prediction + retrieved_contexts. Errors are caught per-case and
       stored on ``case.error``.
    4. Hand the batch to ``evaluator.evaluate(cases)`` to compute RAGAS
       metrics. Errored cases / no-context cases are skipped by the
       evaluator (it returns ``{}`` for those positions).
    5. Build the EvaluationReport with a Summary aggregating the scores.

    ``progress`` is an optional callback (case_idx, total, status) — the
    CLI uses it to print one line per case to stdout.
    """
    # --- Step 1: validate chatbot ---
    chatbot_repo = chatbot_repo_factory(session, ctx)
    try:
        chatbot_row = await chatbot_repo.get(chatbot_id)
    except NotFoundError as exc:
        raise ChatbotNotFoundError(str(exc)) from exc

    # --- Step 2: load dataset ---
    cases = load_evaluation_dataset(dataset_path, scenario_filter=scenario_filter)
    if not cases:
        raise EvaluationError(
            f"Dataset is empty after applying scenario_filter="
            f"{scenario_filter!r}"
        )

    started_at = datetime.now(UTC)
    total = len(cases)

    # --- Step 3: run each case ---
    for idx, case in enumerate(cases):
        if progress is not None:
            progress(idx + 1, total, f"asking: {case.question[:60]}")
        try:
            view = await answer_query(
                session, ctx,
                llm_dispatcher=llm_dispatcher,
                qdrant=qdrant,
                embedder_dispatcher=embedder_dispatcher,
                settings=settings,
                chatbot_id=chatbot_id,
                session_id=None,
                user_message=case.question,
                persist=False,
            )
            case.predicted_answer = view.content
            case.retrieved_contexts = list(view.retrieved_contexts)
            case.citations = [c.to_dict() for c in view.citations]
            case.iterations = [it.to_dict() for it in view.iterations]
        except Exception as exc:  # noqa: BLE001 — record then continue
            case.error = f"{type(exc).__name__}: {exc}"
            _log.warning(
                "run_ragas_evaluation: case %d/%d failed: %s",
                idx + 1, total, exc,
            )

    # --- Step 4: RAGAS metrics ---
    if progress is not None:
        progress(total, total, "scoring with RAGAS...")
    per_case_scores = evaluator.evaluate(cases)
    for case, scores in zip(cases, per_case_scores, strict=True):
        if scores and case.error is None:
            case.scores = scores

    # --- Step 5: build report ---
    finished_at = datetime.now(UTC)
    summary = EvaluationSummary.from_cases(cases)
    report = EvaluationReport(
        chatbot_id=chatbot_id,
        chatbot_name=chatbot_row.name,
        dataset_path=str(dataset_path),
        scenario_filter=scenario_filter,
        run_started_at=started_at,
        run_finished_at=finished_at,
        ragas_judge_model=evaluator.judge_model,
        cases=cases,
        summary=summary,
    )
    return report
