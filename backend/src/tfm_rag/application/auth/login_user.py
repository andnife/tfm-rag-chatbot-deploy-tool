from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.errors.auth import InvalidCredentialsError
from tfm_rag.infrastructure.auth.password import verify_password
from tfm_rag.infrastructure.persistence.repositories.users_repo import (
    UsersByEmailFinder,
)


@dataclass(frozen=True, slots=True)
class LoginUserResult:
    user_id: UUID
    tenant_id: UUID
    email: str


async def login_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
) -> LoginUserResult:
    finder = UsersByEmailFinder(session)
    user = await finder.find_by_email(email)
    if user is None or user.password_hash is None:
        raise InvalidCredentialsError("Invalid email or password")
    if not verify_password(password, user.password_hash):
        raise InvalidCredentialsError("Invalid email or password")
    return LoginUserResult(
        user_id=user.id, tenant_id=user.tenant_id, email=user.email
    )
