"""Incident reporting/query endpoints (Task 4 / T14).

`POST` lets any authenticated user report a client-side incident (the React
`ErrorBoundary` posts here on an uncaught render error) — gated on
authentication only, so any logged-in tenant user can report, and the
report is tagged with their tenant/user for correlation.

`GET` lets an operator inspect recent incidents (server- and client-side).
Gated on superadmin: incidents can embed sensitive detail (stack traces,
sanitized-but-still-internal error text) that must stay cross-tenant-admin
only, not exposed to regular tenant users.

Store: in-memory, process lifetime only (see `error_handler` module
docstring) — it does NOT survive a restart and is NOT shared across
workers. Fine for a single-process dev/demo deployment; swap for a
persistent store before running multiple workers/replicas.
"""
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from tfm_rag.infrastructure.api.dependencies import (
    get_current_context,
    require_superadmin,
)
from tfm_rag.infrastructure.api.error_handler import (
    get_incidents,
    record_client_incident,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


class IncidentIn(BaseModel):
    status_code: int
    error_code: str
    message: str
    detail: Any = None


@router.post("", status_code=201)
async def report_incident(
    body: IncidentIn,
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> dict[str, str]:
    """Record a client-reported incident. Requires an authenticated user
    (any tenant) so the report is attributable and the store can't be
    flooded by unauthenticated clients.
    """
    path = body.detail.get("path", "") if isinstance(body.detail, dict) else ""
    incident = record_client_incident(
        status_code=body.status_code,
        error_code=body.error_code,
        message=body.message,
        detail=body.detail,
        tenant_id=str(ctx.tenant_id),
        user_id=str(ctx.user_id) if ctx.user_id else None,
        path=path,
    )
    return {"id": incident["id"]}


@router.get("", dependencies=[Depends(require_superadmin)])
async def list_incidents(
    limit: int = Query(50, ge=1, le=200),
    status_code: int | None = Query(None, ge=100, le=599),
) -> list[dict[str, Any]]:
    """Return recent error incidents (server- and client-side).

    Superadmin only — see module docstring.
    """
    return get_incidents(limit=limit, status_code=status_code)
