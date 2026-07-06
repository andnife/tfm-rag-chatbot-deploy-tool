import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.infrastructure.api.composition import (
    get_chatbot_repo,
    get_eval_dataset_repo,
    get_eval_run_repo,
)
from tfm_rag.infrastructure.api.dependencies import (
    get_session,
    require_superadmin,
)
from tfm_rag.infrastructure.persistence.models.eval_runs import EvalRunRow
from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
    ChatbotRepository,
)
from tfm_rag.infrastructure.persistence.repositories.eval_datasets_repo import (
    EvalDatasetRepository,
)
from tfm_rag.infrastructure.persistence.repositories.eval_runs_repo import (
    EvalRunRepository,
)

router = APIRouter(
    prefix="/api/admin/eval",
    tags=["admin", "eval"],
    dependencies=[Depends(require_superadmin)],
)

_REPORTS_ROOT = Path("eval_runs")  # cwd-relative, same as eval_reports.py

# ---------------------------------------------------------------------------
# In-process cancel registry
# ---------------------------------------------------------------------------
_CANCEL_REQUESTED: set[str] = set()


def request_cancel(run_id: str) -> None:
    _CANCEL_REQUESTED.add(run_id)


def consume_cancel(run_id: str) -> bool:
    """Return True if a cancel has been requested for *run_id* (non-destructive)."""
    return run_id in _CANCEL_REQUESTED


def clear_cancel(run_id: str) -> None:
    _CANCEL_REQUESTED.discard(run_id)


# Small, fast Ollama model for the inline per-answer correctness check. Kept
# separate from the RAGAS judge (row.judge_model) so live grading stays cheap.
_CORRECTNESS_JUDGE_MODEL = os.environ.get("EVAL_CORRECTNESS_JUDGE_MODEL", "gemma3:1b")


async def _judge_answer_correctness(
    *, question: str, expected: str, predicted: str, model: str, base_url: str
) -> tuple[bool | None, str]:
    """Ask the judge LLM (Ollama) whether ``predicted`` is factually correct vs
    ``expected``. Returns (correct, reason); correct is None if the judge can't
    be reached or returns no parseable JSON. Best-effort — never raises."""
    prompt = (
        "You grade a question-answering system. Decide whether the SYSTEM "
        "answer is factually correct given the REFERENCE answer. Minor wording "
        "differences are fine — judge the facts, not the phrasing.\n\n"
        f"Question: {question}\n"
        f"Reference answer: {expected}\n"
        f"System answer: {predicted}\n\n"
        'Respond with ONLY a JSON object: '
        '{"correct": true or false, "reason": "<one short sentence>"}'
    )
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0},
                },
            )
            resp.raise_for_status()
            data = json.loads(resp.json()["message"]["content"])
            return bool(data.get("correct")), str(data.get("reason", ""))[:300]
    except Exception:  # noqa: BLE001 — judging is best-effort, never break the run
        return None, ""


class EvalRunOut(BaseModel):
    id: str
    chatbot_id: str
    dataset_path: str | None
    dataset_id: str | None = None
    chatbot_name: str | None = None
    dataset_name: str | None = None
    scenario_filter: str | None
    judge_model: str
    generator_model: str | None = None
    status: str
    progress: int
    report_dir: str | None
    error: str | None
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    tokens_gen_in: int | None = None
    tokens_gen_out: int | None = None
    tokens_judge_in: int | None = None
    tokens_judge_out: int | None = None

    @classmethod
    def from_row(
        cls,
        r: EvalRunRow,
        *,
        chatbot_name: str | None = None,
        dataset_name: str | None = None,
        generator_model: str | None = None,
    ) -> "EvalRunOut":
        return cls(
            id=str(r.id), chatbot_id=str(r.chatbot_id), dataset_path=r.dataset_path,
            dataset_id=(str(r.dataset_id) if r.dataset_id else None),
            chatbot_name=chatbot_name, dataset_name=dataset_name,
            scenario_filter=r.scenario_filter,
            judge_model=r.judge_model,
            generator_model=generator_model,
            status=r.status, progress=r.progress, report_dir=r.report_dir,
            error=r.error, created_at=r.created_at, started_at=r.started_at,
            finished_at=r.finished_at,
            tokens_gen_in=r.tokens_gen_in, tokens_gen_out=r.tokens_gen_out,
            tokens_judge_in=r.tokens_judge_in, tokens_judge_out=r.tokens_judge_out,
        )


async def _resolve_run_views(
    rows: list[EvalRunRow],
    *,
    cb_repo: ChatbotRepository,
    ds_repo: EvalDatasetRepository,
) -> list["EvalRunOut"]:
    """Resolve chatbot/dataset names (best-effort, cached) for a list of runs.

    The chatbot fetch also yields ``generator_model`` (its main
    ``llm_selection.model_id``) from the SAME call — no second repo round-trip.
    """
    cb_cache: dict[UUID, tuple[str | None, str | None]] = {}
    ds_cache: dict[UUID, str | None] = {}

    async def _cb_view(cid: UUID) -> tuple[str | None, str | None]:
        """Return (chatbot_name, generator_model) for ``cid``, cached."""
        if cid not in cb_cache:
            try:
                cb = await cb_repo.get(cid)
                # `cb.llm_selection` is the raw JSONB dict on the row
                # ({"credential_id", "model_id"}), not a parsed VO.
                model_id = cb.llm_selection.get("model_id")
                cb_cache[cid] = (cb.name, model_id)
            except NotFoundError:
                cb_cache[cid] = (None, None)
        return cb_cache[cid]

    async def _ds_name(did: UUID | None) -> str | None:
        if did is None:
            return None
        if did not in ds_cache:
            try:
                ds_cache[did] = (await ds_repo.get(did)).name
            except NotFoundError:
                ds_cache[did] = None
        return ds_cache[did]

    out: list[EvalRunOut] = []
    for r in rows:
        cb_name, generator_model = await _cb_view(r.chatbot_id)
        out.append(
            EvalRunOut.from_row(
                r,
                chatbot_name=cb_name,
                dataset_name=await _ds_name(r.dataset_id),
                generator_model=generator_model,
            )
        )
    return out


@router.get("/runs", response_model=list[EvalRunOut])
async def list_runs(
    repo: EvalRunRepository = Depends(get_eval_run_repo),  # noqa: B008
    cb_repo: ChatbotRepository = Depends(get_chatbot_repo),  # noqa: B008
    ds_repo: EvalDatasetRepository = Depends(get_eval_dataset_repo),  # noqa: B008
) -> list[EvalRunOut]:
    rows = await repo.list_recent(limit=50)
    return await _resolve_run_views(rows, cb_repo=cb_repo, ds_repo=ds_repo)


@router.get("/runs/{run_id}", response_model=EvalRunOut)
async def get_run(
    run_id: UUID,
    repo: EvalRunRepository = Depends(get_eval_run_repo),  # noqa: B008
    cb_repo: ChatbotRepository = Depends(get_chatbot_repo),  # noqa: B008
    ds_repo: EvalDatasetRepository = Depends(get_eval_dataset_repo),  # noqa: B008
) -> EvalRunOut:
    try:
        row = await repo.get(run_id)
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"eval run {run_id} not found"
        ) from exc
    views = await _resolve_run_views([row], cb_repo=cb_repo, ds_repo=ds_repo)
    return views[0]


class TraceRowOut(BaseModel):
    """One answered case, streamed live while the run is in progress."""

    idx: int
    total: int
    question: str
    scenario: str | None = None
    ground_truth: str | None = None
    predicted_answer: str | None = None
    iterations: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    retrieved_contexts: list[str] = []
    judged_correct: bool | None = None
    judge_reason: str = ""
    error: str | None = None
    # Live progress fields written by _on_case_with_tokens (absent on legacy rows)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cumulative_prompt_tokens: int | None = None
    cumulative_completion_tokens: int | None = None
    eta_seconds: float | None = None


@router.get("/runs/{run_id}/trace", response_model=list[TraceRowOut])
async def get_run_trace(
    run_id: UUID,
    repo: EvalRunRepository = Depends(get_eval_run_repo),  # noqa: B008
) -> list[TraceRowOut]:
    # Verify the run belongs to the tenant before reading its trace file.
    try:
        await repo.get(run_id)
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"eval run {run_id} not found"
        ) from exc
    trace_path = _REPORTS_ROOT / str(run_id) / "trace.jsonl"
    if not trace_path.is_file():
        return []
    rows: list[TraceRowOut] = []
    with trace_path.open(encoding="utf-8") as fh:
        for raw in fh:
            if not raw.strip():
                continue
            try:
                rows.append(TraceRowOut(**json.loads(raw)))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
    return rows


@router.post("/runs/{run_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    repo: EvalRunRepository = Depends(get_eval_run_repo),  # noqa: B008
) -> dict[str, str]:
    try:
        row = await repo.get(run_id)
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"eval run {run_id} not found"
        ) from exc
    if row.status not in ("queued", "running"):
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"run is {row.status}"
        )
    request_cancel(str(run_id))
    row.status = "cancelled"
    row.finished_at = datetime.now(UTC)
    await session.commit()
    return {"status": "cancelled"}


@router.get("/runs/{run_id}/live")
async def get_run_live(
    run_id: UUID,
    repo: EvalRunRepository = Depends(get_eval_run_repo),  # noqa: B008
) -> dict[str, Any]:
    # Verify the run belongs to the tenant before reading its live file
    # (matches the trace endpoint's ownership check).
    try:
        await repo.get(run_id)
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"eval run {run_id} not found"
        ) from exc
    live_path = _REPORTS_ROOT / str(run_id) / "live.json"
    if not live_path.is_file():
        return {}
    try:
        data: dict[str, Any] = json.loads(live_path.read_text(encoding="utf-8"))
        return data
    except (OSError, json.JSONDecodeError):
        return {}
