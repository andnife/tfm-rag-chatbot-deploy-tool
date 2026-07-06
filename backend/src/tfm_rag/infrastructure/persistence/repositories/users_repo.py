from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.entities.user import User
from tfm_rag.infrastructure.persistence.models.users import UserRow


class UserRepository:
    """Implements `UserRepositoryPort` (see its docstring for the commit
    contract: writes flush, never commit — `get_session` commits the auth
    request's whole unit of work at request end).

    Session-only (no RequestContext): the auth flows are unauthenticated,
    so this deliberately bypasses the tenant-aware `BaseRepository` pattern —
    email/google_sub lookups happen before any tenant is known.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_entity(row: UserRow) -> User:
        return User(
            id=row.id,
            email=row.email,
            password_hash=row.password_hash,
            google_sub=row.google_sub,
            tenant_id=row.tenant_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
            is_superadmin=bool(row.is_superadmin),
        )

    async def find_user_by_email(self, email: str) -> User | None:
        stmt = select(UserRow).where(UserRow.email == email)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._to_entity(row) if row is not None else None

    async def find_user_by_google_sub(self, google_sub: str) -> User | None:
        stmt = select(UserRow).where(UserRow.google_sub == google_sub)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._to_entity(row) if row is not None else None

    async def create_user(
        self,
        *,
        user_id: UUID,
        email: str,
        password_hash: str | None,
        google_sub: str | None,
        tenant_id: UUID,
    ) -> None:
        """Flushes but does NOT commit — see class docstring."""
        self._session.add(
            UserRow(
                id=user_id,
                email=email,
                password_hash=password_hash,
                google_sub=google_sub,
                tenant_id=tenant_id,
            )
        )
        await self._session.flush()

    async def link_google_sub(self, user_id: UUID, google_sub: str) -> None:
        """Flushes but does NOT commit — see class docstring."""
        stmt = select(UserRow).where(UserRow.id == user_id)
        row = (await self._session.execute(stmt)).scalar_one()
        row.google_sub = google_sub
        await self._session.flush()
