import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path as _Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tfm_rag.application.evaluation.dataset_db_loader import load_eval_dataset_from_db
from tfm_rag.application.evaluation.execution_accuracy import execution_accuracy
from tfm_rag.application.evaluation.manage_dataset import (
    create_eval_dataset,
    delete_eval_dataset,
    get_eval_dataset,
    list_eval_datasets,
    process_dataset,
    replace_dataset_rows,
    set_sql_seed,
)
from tfm_rag.application.evaluation.report_writer import write_report
from tfm_rag.application.evaluation.row_import import parse_jsonl_rows
from tfm_rag.application.evaluation.run_ragas_evaluation import run_ragas_evaluation
from tfm_rag.application.integrations.endpoint_resolver import resolve_inference_target
from tfm_rag.application.knowledge.attach_database_source import (
    attach_database_source,
)
from tfm_rag.domain.catalog.eval_scenarios import (
    SCENARIO_ABSTAIN,
    SCENARIO_MIXED,
    SCENARIO_SQL_ONLY,
)
from tfm_rag.domain.catalog.llm_providers import resolve_rate_limits
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.ports.secret_encryptor import SecretEncryptor
from tfm_rag.domain.ports.storage import Storage
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.database_source_spec import DatabaseSourceSpec
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.eval_dataset import EvalDatasetView
from tfm_rag.infrastructure.api.composition import (
    build_answer_query_deps,
    get_chatbot_repo,
    get_credentials_repo,
    get_encryptor,
    get_eval_dataset_item_repo,
    get_eval_dataset_repo,
    get_eval_run_repo,
    get_kb_repo,
    get_qdrant,
    get_sources_repo,
    get_storage,
)
from tfm_rag.infrastructure.api.dependencies import (
    get_current_context,
    get_session,
    get_session_factory,
    require_superadmin,
)
from tfm_rag.infrastructure.api.routers.eval_runs import clear_cancel, consume_cancel
from tfm_rag.infrastructure.database_connectors.source_tester import (
    DATABASE_CONNECTORS,
)
from tfm_rag.infrastructure.evaluation.ragas_evaluator import RagasEvaluator
from tfm_rag.infrastructure.evaluation.sql_provisioner import provision_seed
from tfm_rag.infrastructure.persistence.models.eval_runs import EvalRunRow
from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
    ChatbotRepository,
)
from tfm_rag.infrastructure.persistence.repositories.credentials_repo import (
    ProviderCredentialRepository,
)
from tfm_rag.infrastructure.persistence.repositories.eval_datasets_repo import (
    EvalDatasetItemRepository,
    EvalDatasetRepository,
)
from tfm_rag.infrastructure.persistence.repositories.eval_runs_repo import (
    EvalRunRepository,
)
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repositories.sources_repo import (
    SourceRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.secrets.fernet_encryptor import FernetSecretEncryptor
from tfm_rag.infrastructure.settings import Settings, get_settings
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore

router = APIRouter(
    prefix="/api/admin/eval/datasets",
    tags=["admin", "eval"],
    dependencies=[Depends(require_superadmin)],
)


def _short_detail(detail: dict[str, Any]) -> str:
    """Convert a step-detail dict into a compact one-line summary string."""
    if not detail:
        return ""
    parts = []
    for k, v in detail.items():
        if isinstance(v, list):
            parts.append(f"{k}={len(v)}")
        elif isinstance(v, bool):
            parts.append(f"{k}={v}")
        elif isinstance(v, float):
            parts.append(f"{k}={v:.3g}")
        else:
            parts.append(f"{k}={v}")
    return ", ".join(parts[:4])  # cap at 4 pairs to stay compact


class EvalDatasetOut(BaseModel):
    id: str
    name: str
    description: str | None
    knowledge_base_id: str | None
    db_schema_name: str | None
    status: str
    status_error: str | None
    num_rows: int

    @classmethod
    def from_view(cls, v: EvalDatasetView) -> "EvalDatasetOut":
        return cls(
            id=str(v.id),
            name=v.name,
            description=v.description,
            knowledge_base_id=str(v.knowledge_base_id) if v.knowledge_base_id else None,
            db_schema_name=v.db_schema_name,
            status=v.status,
            status_error=v.status_error,
            num_rows=v.num_rows,
        )


class EvalDatasetRowOut(BaseModel):
    ordinal: int
    question: str
    ground_truth: str
    scenario: str
    complexity: str
    reference_contexts: list[str] | None
    sql_reference: str | None
    source_doc: str | None


class CreateDatasetIn(BaseModel):
    name: str
    description: str | None = None
    embedding_selection: dict[str, Any]
    chunking_config: dict[str, Any] | None = None


class ReplaceRowsIn(BaseModel):
    rows: list[dict[str, Any]]


class ImportRowsIn(BaseModel):
    jsonl: str


@router.post("", response_model=EvalDatasetOut, status_code=status.HTTP_201_CREATED)
async def create(
    body: CreateDatasetIn,
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    ds_repo: EvalDatasetRepository = Depends(get_eval_dataset_repo),  # noqa: B008
    kb_repo: KnowledgeBaseRepository = Depends(get_kb_repo),  # noqa: B008
    qdrant: QdrantStore = Depends(get_qdrant),  # noqa: B008
) -> EvalDatasetOut:
    chunking = (
        ChunkingConfig.from_dict(body.chunking_config)
        if body.chunking_config else ChunkingConfig.default()
    )
    view = await create_eval_dataset(
        ds_repo=ds_repo,
        kb_repo=kb_repo,
        qdrant=qdrant,
        tenant_id=ctx.tenant_id,
        name=body.name,
        description=body.description,
        chunking_config=chunking,
        embedding_selection=EmbeddingSelection.from_dict(body.embedding_selection),
    )
    return EvalDatasetOut.from_view(view)


@router.get("", response_model=list[EvalDatasetOut])
async def list_all(
    ds_repo: EvalDatasetRepository = Depends(get_eval_dataset_repo),  # noqa: B008
    item_repo: EvalDatasetItemRepository = Depends(get_eval_dataset_item_repo),  # noqa: B008
) -> list[EvalDatasetOut]:
    views = await list_eval_datasets(ds_repo=ds_repo, item_repo=item_repo)
    return [EvalDatasetOut.from_view(v) for v in views]


@router.get("/{dataset_id}", response_model=EvalDatasetOut)
async def get_one(
    dataset_id: UUID,
    ds_repo: EvalDatasetRepository = Depends(get_eval_dataset_repo),  # noqa: B008
    item_repo: EvalDatasetItemRepository = Depends(get_eval_dataset_item_repo),  # noqa: B008
) -> EvalDatasetOut:
    return EvalDatasetOut.from_view(
        await get_eval_dataset(ds_repo=ds_repo, item_repo=item_repo, dataset_id=dataset_id)
    )


@router.get("/{dataset_id}/rows", response_model=list[EvalDatasetRowOut])
async def list_rows(
    dataset_id: UUID,
    ds_repo: EvalDatasetRepository = Depends(get_eval_dataset_repo),  # noqa: B008
    item_repo: EvalDatasetItemRepository = Depends(get_eval_dataset_item_repo),  # noqa: B008
) -> list[EvalDatasetRowOut]:
    # tenant-scoped existence check
    await get_eval_dataset(ds_repo=ds_repo, item_repo=item_repo, dataset_id=dataset_id)
    items = await item_repo.list_items_by_dataset(dataset_id)
    return [
        EvalDatasetRowOut(
            ordinal=i.ordinal,
            question=i.question,
            ground_truth=i.ground_truth,
            scenario=i.scenario,
            complexity=i.complexity,
            reference_contexts=i.reference_contexts,
            sql_reference=i.sql_reference,
            source_doc=i.source_doc,
        )
        for i in items
    ]


@router.put("/{dataset_id}/rows", response_model=EvalDatasetOut)
async def replace_rows(
    dataset_id: UUID,
    body: ReplaceRowsIn,
    ds_repo: EvalDatasetRepository = Depends(get_eval_dataset_repo),  # noqa: B008
    item_repo: EvalDatasetItemRepository = Depends(get_eval_dataset_item_repo),  # noqa: B008
) -> EvalDatasetOut:
    view = await replace_dataset_rows(
        ds_repo=ds_repo, item_repo=item_repo, dataset_id=dataset_id, parsed_rows=body.rows
    )
    return EvalDatasetOut.from_view(view)


@router.post("/{dataset_id}/rows/import", response_model=EvalDatasetOut)
async def import_rows(
    dataset_id: UUID,
    body: ImportRowsIn,
    ds_repo: EvalDatasetRepository = Depends(get_eval_dataset_repo),  # noqa: B008
    item_repo: EvalDatasetItemRepository = Depends(get_eval_dataset_item_repo),  # noqa: B008
) -> EvalDatasetOut:
    parsed = parse_jsonl_rows(body.jsonl)
    view = await replace_dataset_rows(
        ds_repo=ds_repo, item_repo=item_repo, dataset_id=dataset_id, parsed_rows=parsed
    )
    return EvalDatasetOut.from_view(view)


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    dataset_id: UUID,
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    ds_repo: EvalDatasetRepository = Depends(get_eval_dataset_repo),  # noqa: B008
    kb_repo: KnowledgeBaseRepository = Depends(get_kb_repo),  # noqa: B008
    sources_repo: SourceRepository = Depends(get_sources_repo),  # noqa: B008
    qdrant: QdrantStore = Depends(get_qdrant),  # noqa: B008
) -> None:
    await delete_eval_dataset(
        ds_repo=ds_repo,
        kb_repo=kb_repo,
        sources_repo=sources_repo,
        qdrant=qdrant,
        tenant_id=ctx.tenant_id,
        dataset_id=dataset_id,
    )


# ---------------------------------------------------------------------------
# New routes: upload SQL seed + process dataset
# ---------------------------------------------------------------------------

class SetSeedIn(BaseModel):
    sql: str


@router.post("/{dataset_id}/sql-seed", response_model=EvalDatasetOut)
async def upload_sql_seed(
    dataset_id: UUID,
    body: SetSeedIn,
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    ds_repo: EvalDatasetRepository = Depends(get_eval_dataset_repo),  # noqa: B008
    item_repo: EvalDatasetItemRepository = Depends(get_eval_dataset_item_repo),  # noqa: B008
    storage: Storage = Depends(get_storage),  # noqa: B008
) -> EvalDatasetOut:
    view = await set_sql_seed(
        ds_repo=ds_repo,
        item_repo=item_repo,
        dataset_id=dataset_id,
        seed_bytes=body.sql.encode("utf-8"),
        storage=storage,
        tenant_id=ctx.tenant_id,
    )
    return EvalDatasetOut.from_view(view)


@router.post("/{dataset_id}/process", response_model=EvalDatasetOut)
async def process(
    dataset_id: UUID,
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    ds_repo: EvalDatasetRepository = Depends(get_eval_dataset_repo),  # noqa: B008
    item_repo: EvalDatasetItemRepository = Depends(get_eval_dataset_item_repo),  # noqa: B008
    kb_repo: KnowledgeBaseRepository = Depends(get_kb_repo),  # noqa: B008
    sources_repo: SourceRepository = Depends(get_sources_repo),  # noqa: B008
    encryptor: SecretEncryptor = Depends(get_encryptor),  # noqa: B008
    storage: Storage = Depends(get_storage),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> EvalDatasetOut:
    async def attach_db(*, kb_id: UUID, spec: DatabaseSourceSpec) -> None:
        await attach_database_source(
            kb_repo=kb_repo,
            sources_repo=sources_repo,
            kb_id=kb_id,
            spec=spec,
            encryptor=encryptor,
            connectors=DATABASE_CONNECTORS,
        )

    view = await process_dataset(
        ds_repo=ds_repo,
        item_repo=item_repo,
        dataset_id=dataset_id,
        storage=storage,
        seed_provisioner=provision_seed,
        attach_db=attach_db,
        mysql_cfg={
            "host": settings.eval_mysql_host,
            "port": settings.eval_mysql_port,
            "admin_user": settings.eval_mysql_admin_user,
            "admin_password": settings.eval_mysql_admin_password,
        },
    )
    return EvalDatasetOut.from_view(view)


# ---------------------------------------------------------------------------
# Entity-dataset run routes
# ---------------------------------------------------------------------------

_log = logging.getLogger(__name__)

_REPORTS_ROOT = _Path("eval_runs")

# Connections to keep free for the live API (progress polls, other requests)
# while an eval saturates the pool with per-case sessions.
_DB_POOL_API_RESERVE = 10
# If more than this fraction of cases fail to GENERATE (case.error set — a
# pipeline/infra failure, not a low score), the run is unreliable and is marked
# `failed` instead of `done`.
_MAX_GEN_ERROR_RATE = 0.1

# Rough number of judge LLM calls RAGAS makes per scorable (non-abstain) row
# across its 4 metrics. Only used to estimate the live scoring-progress total;
# the bar clamps to 99% so an imperfect estimate never fakes completion.
_JUDGE_CALLS_PER_SCORABLE_ROW = 6


class CreateEntityRunIn(BaseModel):
    chatbot_id: UUID
    judge_model: str
    judge_credential_id: UUID
    # Baseline mode: disable the router and force the docs route (naive RAG),
    # for the platform-vs-baseline contrast. Default = full pipeline.
    router_disabled: bool = False


class EntityEvalRunOut(BaseModel):
    id: str
    chatbot_id: str
    dataset_path: str | None
    scenario_filter: str | None
    judge_model: str
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
    def from_row(cls, r: EvalRunRow) -> "EntityEvalRunOut":
        return cls(
            id=str(r.id),
            chatbot_id=str(r.chatbot_id),
            dataset_path=r.dataset_path,
            scenario_filter=r.scenario_filter,
            judge_model=r.judge_model,
            status=r.status,
            progress=r.progress,
            report_dir=r.report_dir,
            error=r.error,
            created_at=r.created_at,
            started_at=r.started_at,
            finished_at=r.finished_at,
            tokens_gen_in=r.tokens_gen_in,
            tokens_gen_out=r.tokens_gen_out,
            tokens_judge_in=r.tokens_judge_in,
            tokens_judge_out=r.tokens_judge_out,
        )


@router.post(
    "/{dataset_id}/runs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=EntityEvalRunOut,
)
async def create_entity_run(
    dataset_id: UUID,
    body: CreateEntityRunIn,
    background_tasks: BackgroundTasks,
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    chatbot_repo: ChatbotRepository = Depends(get_chatbot_repo),  # noqa: B008
    ds_repo: EvalDatasetRepository = Depends(get_eval_dataset_repo),  # noqa: B008
    item_repo: EvalDatasetItemRepository = Depends(get_eval_dataset_item_repo),  # noqa: B008
    run_repo: EvalRunRepository = Depends(get_eval_run_repo),  # noqa: B008
) -> EntityEvalRunOut:
    """Trigger a RAGAS evaluation run for a DB-entity dataset. Returns 202 immediately."""
    # Validate chatbot exists in this tenant.
    try:
        await chatbot_repo.get(body.chatbot_id)
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"chatbot {body.chatbot_id} not found",
        ) from exc

    # Load dataset to verify it exists and capture kb_id *before* commit
    # (ORM attributes expire after commit — capture them now).
    cases, kb_id = await load_eval_dataset_from_db(
        ds_repo=ds_repo, item_repo=item_repo, dataset_id=dataset_id
    )
    if not cases:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="dataset has no rows — import rows before running evaluation",
        )

    run_id = uuid4()
    row = EvalRunRow(
        id=run_id,
        tenant_id=ctx.tenant_id,
        chatbot_id=body.chatbot_id,
        dataset_id=dataset_id,
        dataset_path=None,
        scenario_filter=None,
        judge_model=body.judge_model,
        judge_credential_id=body.judge_credential_id,
        status="queued",
        progress=0,
    )
    await run_repo.add(row)
    await session.commit()

    factory = get_session_factory(settings)
    out = EntityEvalRunOut.from_row(row)

    kb_ids_override = [kb_id] if kb_id else None

    async def _kick() -> None:
        await _run_entity_eval_in_background(
            factory=factory,
            settings=settings,
            run_id=run_id,
            tenant_id=ctx.tenant_id,
            dataset_id=dataset_id,
            kb_ids_override=kb_ids_override,
            judge_credential_id=body.judge_credential_id,
            router_disabled=body.router_disabled,
        )

    background_tasks.add_task(_kick)
    return out


async def _run_entity_eval_in_background(
    *,
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    run_id: UUID,
    tenant_id: UUID,
    dataset_id: UUID,
    kb_ids_override: list[UUID] | None,
    judge_credential_id: UUID,
    router_disabled: bool = False,
) -> None:
    qdrant = QdrantStore(settings.qdrant_url, settings.qdrant_api_key)
    try:
        async with factory() as session:
            ctx = RequestContext(tenant_id=tenant_id)
            row = await EvalRunRepository(session, ctx).get(run_id)

            row.status = "running"
            row.started_at = datetime.now(UTC)
            await session.commit()

            trace_path = _REPORTS_ROOT / str(run_id) / "trace.jsonl"
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            live_path = _REPORTS_ROOT / str(run_id) / "live.json"

            # Running totals for enhanced trace fields
            cumulative_prompt: list[int] = [0]
            cumulative_completion: list[int] = [0]
            case_times: list[float] = []
            last_case_start: list[float] = [time.monotonic()]

            # Live per-step progress state
            _q_started: list[float] = [time.monotonic()]
            _cur: dict[str, Any] = {
                "index": 0, "total": 0, "question": "",
                "current_step": "", "steps": [], "started_at": None,
            }

            async def _on_step(
                idx: int, total: int, step: str, detail: dict[str, Any]
            ) -> None:
                if _cur["index"] != idx:
                    _cur.update(
                        index=idx, total=total, question="",
                        current_step=step, steps=[],
                        started_at=datetime.now(UTC).isoformat(),
                    )
                    _q_started[0] = time.monotonic()
                _cur["current_step"] = step
                _cur["steps"].append({
                    "step": step,
                    "detail": _short_detail(detail),
                    "elapsed_ms": round((time.monotonic() - _q_started[0]) * 1000, 1),
                })
                try:
                    live_path.write_text(json.dumps(_cur, ensure_ascii=False), encoding="utf-8")
                except OSError:
                    pass

            async def _should_cancel() -> bool:
                return consume_cancel(str(run_id))

            async def _on_case_with_tokens(
                case: dict[str, Any], idx: int, total: int
            ) -> None:
                elapsed = time.monotonic() - last_case_start[0]
                case_times.append(elapsed)
                last_case_start[0] = time.monotonic()

                pt = case.get("prompt_tokens") or 0
                ct = case.get("completion_tokens") or 0
                cumulative_prompt[0] += pt
                cumulative_completion[0] += ct

                # ETA: moving avg seconds/case × remaining cases
                remaining = total - idx
                avg_secs = sum(case_times) / len(case_times) if case_times else 0.0
                eta_seconds = avg_secs * remaining

                record = {
                    # `idx` arrives 1-based (run loop passes idx+1); store it
                    # 0-based so the frontend's `#{row.idx + 1}` label numbers
                    # questions #1..#N.
                    "idx": idx - 1,
                    "total": total,
                    "question": case.get("question"),
                    "scenario": case.get("scenario"),
                    "ground_truth": case.get("ground_truth"),
                    "predicted_answer": case.get("predicted_answer"),
                    "iterations": case.get("iterations", []),
                    "citations": case.get("citations", []),
                    "retrieved_contexts": case.get("retrieved_contexts", []),
                    "error": case.get("error"),
                    "prompt_tokens": pt,
                    "completion_tokens": ct,
                    "cumulative_prompt_tokens": cumulative_prompt[0],
                    "cumulative_completion_tokens": cumulative_completion[0],
                    "eta_seconds": round(eta_seconds, 1),
                }
                with trace_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")

            try:
                # Reload cases fresh in background session (fresh-session
                # semantics preserved — the job owns its own session/repos).
                cases, _kb_id = await load_eval_dataset_from_db(
                    ds_repo=EvalDatasetRepository(session, ctx),
                    item_repo=EvalDatasetItemRepository(session, ctx),
                    dataset_id=dataset_id,
                )

                # --- Resume: skip cases already generated in a prior attempt.
                # The run's trace.jsonl records one line per completed case
                # (0-based `idx`); parse it, load that data back onto `cases`
                # (so the final report/scoring includes them), and hand the set
                # of done indices to the pipeline so it won't re-generate them.
                resume_done_indices: set[int] = set()
                if trace_path.exists():
                    for _line in trace_path.read_text(encoding="utf-8").splitlines():
                        _line = _line.strip()
                        if not _line:
                            continue
                        try:
                            _rec = json.loads(_line)
                        except json.JSONDecodeError:
                            continue
                        _ridx = _rec.get("idx")
                        if not isinstance(_ridx, int) or not (0 <= _ridx < len(cases)):
                            continue
                        resume_done_indices.add(_ridx)
                        _c = cases[_ridx]
                        _c.predicted_answer = _rec.get("predicted_answer")
                        _c.retrieved_contexts = _rec.get("retrieved_contexts") or []
                        _c.citations = _rec.get("citations") or []
                        _c.iterations = _rec.get("iterations") or []
                        _c.prompt_tokens = _rec.get("prompt_tokens") or 0
                        _c.completion_tokens = _rec.get("completion_tokens") or 0
                        _c.error = _rec.get("error")
                        _c.total_latency_ms = (
                            sum(it.get("latency_ms", 0.0) for it in _c.iterations)
                            if _c.iterations else 0.0
                        )
                # Seed cumulative token counters so appended trace lines for the
                # newly-generated cases keep monotonic running totals.
                cumulative_prompt[0] = sum(
                    cases[i].prompt_tokens for i in resume_done_indices
                )
                cumulative_completion[0] = sum(
                    cases[i].completion_tokens for i in resume_done_indices
                )

                # Resolve judge endpoint from credential.
                credentials_repo = ProviderCredentialRepository(session, ctx)
                judge_provider_id, judge_base_url, judge_api_key = await resolve_inference_target(
                    credential_id=judge_credential_id,
                    credentials_repo=credentials_repo,
                    encryptor=FernetSecretEncryptor(settings.fernet_key),
                    ollama_base_url=settings.ollama_base_url,
                )
                # The judge credential's rate limit sizes RAGAS concurrency.
                judge_cred = await credentials_repo.get(judge_credential_id)

                # --- Live scoring progress (the RAGAS phase is one blocking
                # batch with no per-item events, so we drive the bar off the
                # judge-call count via the token callback). ---
                _scorable = sum(1 for c in cases if c.scenario != SCENARIO_ABSTAIN)
                _abstain = len(cases) - _scorable
                _scoring_total = max(
                    1, _scorable * _JUDGE_CALLS_PER_SCORABLE_ROW + _abstain
                )
                _scoring_t0 = [0.0]
                _scoring_last = [0.0]

                def _write_scoring(done: int) -> None:
                    now = time.monotonic()
                    if _scoring_t0[0] == 0.0:
                        _scoring_t0[0] = now
                    # Throttle mid-phase writes to ~1.5/s; always emit the first
                    # (done==0) and the final (done>=total) states.
                    if 0 < done < _scoring_total and (now - _scoring_last[0]) < 0.7:
                        return
                    _scoring_last[0] = now
                    elapsed = now - _scoring_t0[0]
                    rate = done / elapsed if elapsed > 0 and done > 0 else 0.0
                    eta = max(0.0, _scoring_total - done) / rate if rate > 0 else None
                    payload = {
                        "phase": "scoring",
                        "scoring_done": done,
                        "scoring_total": _scoring_total,
                        "elapsed_seconds": round(elapsed, 1),
                        "eta_seconds": round(eta, 1) if eta is not None else None,
                    }
                    tmp = live_path.with_suffix(".json.tmp")
                    try:
                        tmp.write_text(
                            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
                        )
                        tmp.replace(live_path)  # atomic
                    except OSError:
                        pass

                def _progress(idx: int, total: int, status: str) -> None:
                    # run_ragas_evaluation calls this with a "scoring..." status
                    # right before the batch begins; publish the initial state.
                    if "scoring" in status.lower():
                        _scoring_t0[0] = time.monotonic()
                        _write_scoring(0)

                judge_max_workers, judge_min_interval = resolve_rate_limits(
                    judge_provider_id,
                    cred_max_concurrency=judge_cred.max_concurrency,
                    cred_min_interval=judge_cred.min_request_interval_seconds,
                )
                evaluator = RagasEvaluator(
                    base_url=settings.ollama_base_url,
                    judge_model=row.judge_model,
                    embedding_model="bge-m3",
                    judge_provider=judge_provider_id,
                    judge_base_url=judge_base_url,
                    judge_api_key=judge_api_key,
                    max_workers=judge_max_workers,
                    min_request_interval_seconds=judge_min_interval,
                    on_judge_progress=_write_scoring,
                )
                answer_deps = build_answer_query_deps(session, ctx, settings, qdrant)

                # Concurrency: overlap the many slow generation calls, sized by
                # the chatbot's generation credential rate limit (fall back to
                # sequential when unset). Concurrent cases MUST each get a fresh
                # session — a shared AsyncSession raises asyncpg "another
                # operation in progress" — so we hand the pipeline a factory
                # that opens one session per case (the `both`-route fix).
                gen_chatbot = await answer_deps["chatbot_repo"].get_chatbot(row.chatbot_id)
                gen_cred = await credentials_repo.get(
                    gen_chatbot.llm_selection.credential_id
                )
                gen_concurrency = gen_cred.max_concurrency or 1
                # Align concurrency with the DB pool: each in-flight case holds
                # one connection, so we can never run more cases at once than the
                # pool serves (minus a reserve for the live API). This keeps runs
                # from exhausting the pool no matter how high a credential's
                # max_concurrency is — raise db_pool_size/db_max_overflow to go
                # faster.
                _pool_total = settings.db_pool_size + settings.db_max_overflow
                _max_eval_concurrency = max(1, _pool_total - _DB_POOL_API_RESERVE)
                if gen_concurrency > _max_eval_concurrency:
                    _log.info(
                        "eval run %s: clamping generation concurrency %d -> %d "
                        "(DB pool total=%d, reserve=%d)",
                        run_id, gen_concurrency, _max_eval_concurrency,
                        _pool_total, _DB_POOL_API_RESERVE,
                    )
                    gen_concurrency = _max_eval_concurrency

                @asynccontextmanager
                async def _make_case_deps() -> AsyncIterator[dict[str, Any]]:
                    async with factory() as case_session:
                        case_ctx = RequestContext(tenant_id=tenant_id)
                        yield build_answer_query_deps(
                            case_session, case_ctx, settings, qdrant
                        )

                # Execution accuracy (SQL correctness): run the gold sql_reference
                # and the model's final SQL against the SAME DB source (comparable
                # rows) and compare multisets. Best-effort — any failure yields no
                # score for that case rather than breaking the run.
                _qdb = answer_deps["query_database_fn"]
                _kb_ids = tuple(kb_ids_override or [])
                _db_source_id = None
                for _kb in _kb_ids:
                    _dbs = [s for s in await answer_deps["sources_repo"]
                            .list_sources_by_kb(_kb) if s.type == "database"]
                    if _dbs:
                        _db_source_id = _dbs[0].id
                        break

                async def _exec_scorer(case: Any) -> float | None:
                    if case.scenario not in (SCENARIO_SQL_ONLY, SCENARIO_MIXED):
                        return None
                    ref = (case.metadata or {}).get("sql_reference")
                    if not ref or _db_source_id is None:
                        return None
                    # The self-terminating SQL loop runs several queries with no
                    # explicit "answer" query, so credit the case if ANY query it
                    # executed successfully reproduces the reference answer. (Taking
                    # only the last query mis-scored cases whose last call was a
                    # discovery/refinement query.)
                    preds = [
                        it["sql"] for it in (case.iterations or [])
                        if it.get("sql") and it.get("row_count") is not None
                    ]
                    if not preds:
                        return None
                    try:
                        ref_out = await _qdb(allowed_kb_ids=_kb_ids,
                                             source_id=_db_source_id, sql=ref, row_limit=500)
                        ref_rows = [dict(r) for r in ref_out.result.rows]
                    except Exception:  # noqa: BLE001 — best-effort metric
                        return None
                    best = 0.0
                    for sql in preds:
                        try:
                            pred_out = await _qdb(allowed_kb_ids=_kb_ids,
                                                  source_id=_db_source_id, sql=sql, row_limit=500)
                        except Exception:  # noqa: BLE001, S112 — skip a failing candidate query
                            continue
                        best = max(best, execution_accuracy(
                            [dict(r) for r in pred_out.result.rows], ref_rows,
                        ))
                        if best >= 1.0:
                            break
                    return best

                report = await run_ragas_evaluation(
                    chatbot_repo=answer_deps["chatbot_repo"],
                    answer_query_deps=answer_deps,
                    evaluator=evaluator,
                    chatbot_id=row.chatbot_id,
                    dataset_path=_Path(f"entity:{dataset_id}"),
                    scenario_filter=None,
                    progress=_progress,
                    on_case=_on_case_with_tokens,
                    on_step=_on_step,
                    should_cancel=_should_cancel,
                    cases=cases,
                    kb_ids_override=kb_ids_override,
                    execution_scorer=_exec_scorer,
                    router_disabled=router_disabled,
                    concurrency=gen_concurrency,
                    # Keep the single-session path for concurrency==1 (pass the
                    # factory only when actually parallelising).
                    make_case_deps=(
                        _make_case_deps if gen_concurrency > 1 else None
                    ),
                    resume_done_indices=resume_done_indices,
                )
                # Guard: if cancel was requested while the run was executing,
                # the endpoint already set status='cancelled'; do NOT overwrite
                # with 'done'. consume_cancel returns True if cancel was requested
                # (it is non-destructive; clear_cancel in finally does the cleanup).
                if consume_cancel(str(run_id)):
                    row.status = "cancelled"
                    row.finished_at = datetime.now(UTC)
                    await session.commit()
                else:
                    out_dir = _REPORTS_ROOT / str(run_id)
                    write_report(report, output_dir=out_dir, timestamped=False)

                    summary = report.summary
                    judge_prompt = evaluator.last_judge_prompt_tokens
                    judge_completion = evaluator.last_judge_completion_tokens

                    row.tokens_gen_in = summary.gen_prompt_tokens
                    row.tokens_gen_out = summary.gen_completion_tokens
                    row.tokens_judge_in = judge_prompt
                    row.tokens_judge_out = judge_completion
                    # A run whose cases largely failed to GENERATE (pipeline/infra
                    # errors, not low scores) is not a valid result — mark it
                    # `failed`, not `done`. The report is still written so the
                    # partial output can be inspected.
                    error_rate = (
                        summary.num_errors / summary.num_cases
                        if summary.num_cases else 0.0
                    )
                    if error_rate > _MAX_GEN_ERROR_RATE:
                        row.status = "failed"
                        row.error = (
                            f"{summary.num_errors}/{summary.num_cases} casos "
                            "fallaron en generación (error de pipeline, no puntuación)."
                        )
                    else:
                        row.status = "done"
                    row.progress = 100
                    row.report_dir = str(run_id)
                    row.finished_at = datetime.now(UTC)
                    await session.commit()
            except Exception as exc:  # noqa: BLE001
                # If a cancel was requested, honor it even when the run raised
                # while finishing (e.g. the judge call on the partial set after
                # a cooperative break) — don't clobber the user's 'cancelled'
                # with 'failed'. consume_cancel is non-destructive.
                if consume_cancel(str(run_id)):
                    row.status = "cancelled"
                else:
                    row.status = "failed"
                    row.error = str(exc)[:1900]
                row.finished_at = datetime.now(UTC)
                await session.commit()
            finally:
                live_path.unlink(missing_ok=True)
                clear_cancel(str(run_id))
    finally:
        await qdrant.close()


# ---------------------------------------------------------------------------
# Calibration route
# ---------------------------------------------------------------------------

class CalibrateIn(BaseModel):
    chatbot_id: UUID
    judge_model: str
    judge_credential_id: UUID
    sample_size: int = 3


@router.post("/{dataset_id}/calibrate")
async def calibrate_dataset(
    dataset_id: UUID,
    body: CalibrateIn,
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    chatbot_repo: ChatbotRepository = Depends(get_chatbot_repo),  # noqa: B008
    ds_repo: EvalDatasetRepository = Depends(get_eval_dataset_repo),  # noqa: B008
    item_repo: EvalDatasetItemRepository = Depends(get_eval_dataset_item_repo),  # noqa: B008
    credentials_repo: ProviderCredentialRepository = Depends(get_credentials_repo),  # noqa: B008
    encryptor: SecretEncryptor = Depends(get_encryptor),  # noqa: B008
    qdrant: QdrantStore = Depends(get_qdrant),  # noqa: B008
) -> dict[str, Any]:
    """Run a SYNCHRONOUS mini-eval over `sample_size` rows and extrapolate cost/time."""
    # Validate chatbot
    try:
        await chatbot_repo.get(body.chatbot_id)
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"chatbot {body.chatbot_id} not found",
        ) from exc

    all_cases, kb_id = await load_eval_dataset_from_db(
        ds_repo=ds_repo, item_repo=item_repo, dataset_id=dataset_id
    )
    if not all_cases:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="dataset has no rows",
        )

    total_rows = len(all_cases)
    sample_size = min(body.sample_size, total_rows)
    sample_cases = all_cases[:sample_size]
    kb_ids_override = [kb_id] if kb_id else None

    # Resolve judge endpoint from credential.
    cal_judge_provider_id, cal_judge_base_url, cal_judge_api_key = await resolve_inference_target(
        credential_id=body.judge_credential_id,
        credentials_repo=credentials_repo,
        encryptor=encryptor,
        ollama_base_url=settings.ollama_base_url,
    )
    cal_judge_cred = await credentials_repo.get(body.judge_credential_id)

    cal_max_workers, cal_min_interval = resolve_rate_limits(
        cal_judge_provider_id,
        cred_max_concurrency=cal_judge_cred.max_concurrency,
        cred_min_interval=cal_judge_cred.min_request_interval_seconds,
    )
    evaluator = RagasEvaluator(
        base_url=settings.ollama_base_url,
        judge_model=body.judge_model,
        embedding_model="bge-m3",
        judge_provider=cal_judge_provider_id,
        judge_base_url=cal_judge_base_url,
        judge_api_key=cal_judge_api_key,
        max_workers=cal_max_workers,
        min_request_interval_seconds=cal_min_interval,
    )
    answer_deps = build_answer_query_deps(session, ctx, settings, qdrant)
    t0 = time.monotonic()
    report = await run_ragas_evaluation(
        chatbot_repo=answer_deps["chatbot_repo"],
        answer_query_deps=answer_deps,
        evaluator=evaluator,
        chatbot_id=body.chatbot_id,
        dataset_path=_Path(f"calibrate:{dataset_id}"),
        scenario_filter=None,
        cases=sample_cases,
        kb_ids_override=kb_ids_override,
    )
    elapsed = time.monotonic() - t0

    summary = report.summary
    judge_prompt = evaluator.last_judge_prompt_tokens
    judge_completion = evaluator.last_judge_completion_tokens

    total_gen_tokens = summary.gen_prompt_tokens + summary.gen_completion_tokens
    total_judge_tokens = judge_prompt + judge_completion

    avg_gen_tokens = total_gen_tokens // sample_size if sample_size else 0
    avg_judge_tokens = total_judge_tokens // sample_size if sample_size else 0
    avg_seconds = elapsed / sample_size if sample_size else 0.0

    projected_tokens = (avg_gen_tokens + avg_judge_tokens) * total_rows
    projected_seconds = avg_seconds * total_rows

    return {
        "sample_size": sample_size,
        "avg_gen_tokens": avg_gen_tokens,
        "avg_judge_tokens": avg_judge_tokens,
        "avg_seconds": round(avg_seconds, 2),
        "projected_total": {
            "tokens": projected_tokens,
            "seconds": round(projected_seconds, 1),
        },
    }
