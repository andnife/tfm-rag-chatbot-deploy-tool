from dataclasses import dataclass
from typing import ClassVar, TypeVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.infrastructure.persistence.base import Base

E = TypeVar("E", bound=Base)


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Carries the authenticated tenant/user for the lifetime of a request.

    Repositories receive this and MUST filter by tenant_id on every read/write.
    The tenant filter is wired in plan 02 (CAP-INFRA-TENANT-ISOLATION); this
    class is the carrier defined in plan 01.
    """
    tenant_id: UUID
    user_id: UUID | None = None


class BaseRepository[E: Base]:
    """Generic repository skeleton.

    Subclasses must set `model = <SQLAlchemy entity class>`. CRUD helpers
    are added in plan 02 once the tenant filter is wired.
    """
    model: ClassVar[type]  # set by subclasses to a Base-derived class

    def __init__(self, session: AsyncSession, ctx: RequestContext) -> None:
        self._session = session
        self._ctx = ctx
