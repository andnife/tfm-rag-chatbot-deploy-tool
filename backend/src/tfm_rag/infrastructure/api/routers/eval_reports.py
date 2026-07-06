"""Read-only endpoints to surface RAGAS evaluation reports written to disk
by the CLI (``eval-ragas``). The CLI writes ``report.json`` + ``report.md``
inside ``eval_runs/<UTC-timestamp>/`` (cwd-relative), so when uvicorn runs
from the backend directory, those land in ``backend/eval_runs/``.

These endpoints are tenant-scoped at the auth layer (the middleware
requires a bearer token) but the reports themselves are not stored per
tenant — they're whatever the CLI produced. Treat this as an admin
surface for the local dev/demo flow.
"""
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from tfm_rag.infrastructure.api.dependencies import require_superadmin

router = APIRouter(
    prefix="/api/admin/eval",
    tags=["admin", "eval"],
    dependencies=[Depends(require_superadmin)],
)


# Resolve eval_runs/ relative to the cwd, which for uvicorn is the backend
# dir. We resolve once at module load time but tolerate it not existing
# yet — the directory is created by the first eval-ragas run.
_REPORTS_ROOT = Path("eval_runs")


class ReportSummary(BaseModel):
    name: str
    has_json: bool
    has_markdown: bool


@router.get("/reports", response_model=list[ReportSummary])
async def list_reports(
    limit: int = Query(50, ge=1, le=500),
) -> list[ReportSummary]:
    # Local-disk admin/dev endpoint (not a hot path): blocking pathlib calls
    # are fine here, not worth an asyncio.to_thread indirection.
    if not _REPORTS_ROOT.exists():  # noqa: ASYNC240
        return []
    entries: list[ReportSummary] = []
    for child in sorted(
        _REPORTS_ROOT.iterdir(),  # noqa: ASYNC240
        key=lambda p: p.name,
        reverse=True,
    ):
        if not child.is_dir():
            continue
        has_json = (child / "report.json").is_file()
        has_markdown = (child / "report.md").is_file()
        # Skip in-progress / empty run dirs (created at run start, report written
        # only on completion) — they have nothing to view yet.
        if not has_json and not has_markdown:
            continue
        entries.append(
            ReportSummary(
                name=child.name,
                has_json=has_json,
                has_markdown=has_markdown,
            )
        )
        if len(entries) >= limit:
            break
    return entries


def _safe_report_dir(name: str) -> Path:
    """Resolve `eval_runs/<name>` ensuring the result stays inside the root.

    Defends against path traversal (`..`, absolute paths, symlink escape).
    """
    root = _REPORTS_ROOT.resolve() if _REPORTS_ROOT.exists() else None
    candidate = (_REPORTS_ROOT / name).resolve()
    if root is None or not str(candidate).startswith(str(root) + "/") and candidate != root:
        # Either root doesn't exist or `candidate` is outside it.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"Report {name!r} not found"
        )
    if not candidate.is_dir():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"Report {name!r} not found"
        )
    return candidate


@router.get("/reports/{name}/markdown")
async def get_report_markdown(name: str) -> dict[str, str]:
    report_dir = _safe_report_dir(name)
    md_path = report_dir / "report.md"
    if not md_path.is_file():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="report.md not found"
        )
    return {"content": md_path.read_text(encoding="utf-8")}


@router.get("/reports/{name}/json")
async def get_report_json(name: str) -> dict[str, Any]:
    report_dir = _safe_report_dir(name)
    json_path = report_dir / "report.json"
    if not json_path.is_file():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="report.json not found"
        )
    try:
        data: dict[str, Any] = json.loads(json_path.read_text(encoding="utf-8"))
        return data
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"report.json is malformed: {exc}",
        ) from exc
