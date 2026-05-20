from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.auth.bootstrap_tenant import bootstrap_tenant
from tfm_rag.domain.errors.auth import UserAlreadyExistsError
from tfm_rag.infrastructure.auth.password import hash_password
from tfm_rag.infrastructure.persistence.models.users import UserRow
from tfm_rag.infrastructure.persistence.repositories.users_repo import (
    UsersByEmailFinder,
)


@dataclass(frozen=True, slots=True)
class RegisterUserResult:
    user_id: UUID
    tenant_id: UUID
    email: str


async def register_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
) -> RegisterUserResult:
    finder = UsersByEmailFinder(session)
    if await finder.find_by_email(email) is not None:
        raise UserAlreadyExistsError(f"Email {email} already registered")

    bt = await bootstrap_tenant(session, name=email)

    user_id = uuid4()
    row = UserRow(
        id=user_id,
        email=email,
        password_hash=hash_password(password),
        google_sub=None,
        tenant_id=bt.tenant_id,
    )
    session.add(row)
    await session.flush()
    return RegisterUserResult(
        user_id=user_id, tenant_id=bt.tenant_id, email=email
    )
