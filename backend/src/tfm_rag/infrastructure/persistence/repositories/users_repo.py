from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.infrastructure.persistence.models.users import UserRow


class UsersByEmailFinder:
    """Email-based lookup is unauthenticated (used during login), so it
    bypasses the standard tenant-aware repository pattern.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_email(self, email: str) -> UserRow | None:
        stmt = select(UserRow).where(UserRow.email == email)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def find_by_google_sub(self, google_sub: str) -> UserRow | None:
        stmt = select(UserRow).where(UserRow.google_sub == google_sub)
        return (await self._session.execute(stmt)).scalar_one_or_none()
