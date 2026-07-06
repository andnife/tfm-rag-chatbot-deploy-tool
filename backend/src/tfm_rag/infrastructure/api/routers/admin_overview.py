"""Cross-tenant, read-only admin overview endpoints (superadmin only).

Gated by `require_superadmin` at the router level. See
`application/admin/overview.py` for the queries and the metadata-only rule.
"""
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.admin import overview as ov
from tfm_rag.infrastructure.api.dependencies import (
    get_session,
    require_superadmin,
)
from tfm_rag.infrastructure.persistence.repositories.admin_overview_repo import (
    AdminOverviewReader,
)

router = APIRouter(
    prefix="/api/admin/overview",
    tags=["admin"],
    dependencies=[Depends(require_superadmin)],
)


@router.get("/tenants")
async def list_tenants(
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[dict[str, Any]]:
    overviews = await ov.list_tenants_with_users(reader=AdminOverviewReader(session))
    return [
        {
            "tenant_id": str(o.tenant_id),
            "name": o.name,
            "users": [
                {
                    "id": str(u.id),
                    "email": u.email,
                    "is_superadmin": u.is_superadmin,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                }
                for u in o.users
            ],
        }
        for o in overviews
    ]


@router.get("/tenants/{tenant_id}")
async def tenant_detail(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    detail = await ov.tenant_detail(
        reader=AdminOverviewReader(session), tenant_id=tenant_id
    )
    return {
        "tenant_id": str(detail.tenant_id),
        "chatbots": [
            {"id": str(c.id), "name": c.name, "description": c.description}
            for c in detail.chatbots
        ],
        "knowledge_bases": [
            {"id": str(k.id), "name": k.name, "description": k.description}
            for k in detail.knowledge_bases
        ],
        "credentials": [
            {
                "id": str(c.id),
                "provider_id": c.provider_id,
                "label": c.label,
                "base_url": c.base_url,
                "config_source": c.config_source,
            }
            for c in detail.credentials
        ],
    }
