from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.common import NotFoundError, TenantScopeViolation
from tfm_rag.infrastructure.persistence.base import Base


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Carries the authenticated tenant/user for the lifetime of a request."""
    tenant_id: UUID
    user_id: UUID | None = None


class BaseRepository[E: Base]:
    """Generic tenant-aware repository.

    Subclasses MUST set `model = <ORM class>` AND that ORM class MUST have a
    `tenant_id` column (defense in depth: every model under tenant scoping
    carries the column directly).
    """

    model: ClassVar[type]

    def __init__(self, session: AsyncSession, ctx: RequestContext) -> None:
        self._session = session
        self._ctx = ctx

    def _check_tenant(self, row: object) -> None:
        row_tenant = getattr(row, "tenant_id", None)
        if row_tenant is None:
            raise TenantScopeViolation(
                f"{type(row).__name__} has no tenant_id; refusing to operate."
            )
        if row_tenant != self._ctx.tenant_id:
            raise TenantScopeViolation(
                f"Row tenant {row_tenant!s} != context tenant {self._ctx.tenant_id!s}."
            )

    async def add(self, row: E) -> E:
        """Persist a row. Caller must set row.tenant_id = ctx.tenant_id."""
        self._check_tenant(row)
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, row_id: UUID) -> E:
        stmt = select(self.model).where(
            self.model.id == row_id,  # type: ignore[attr-defined]
            self.model.tenant_id == self._ctx.tenant_id,  # type: ignore[attr-defined]
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"{self.model.__name__}({row_id}) not found in tenant")
        return row

    async def list(self, *, limit: int = 20, offset: int = 0) -> list[E]:
        stmt = (
            select(self.model)
            .where(self.model.tenant_id == self._ctx.tenant_id)  # type: ignore[attr-defined]
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, row_id: UUID) -> None:
        stmt = delete(self.model).where(
            self.model.id == row_id,  # type: ignore[attr-defined]
            self.model.tenant_id == self._ctx.tenant_id,  # type: ignore[attr-defined]
        )
        result = await self._session.execute(stmt)
        if result.rowcount == 0:
            raise NotFoundError(f"{self.model.__name__}({row_id}) not found in tenant")
