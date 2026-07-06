from dataclasses import dataclass
from uuid import UUID

from tfm_rag.domain.errors.auth import InvalidCredentialsError
from tfm_rag.domain.ports.password_hasher import PasswordHasher
from tfm_rag.domain.ports.repositories import UserRepositoryPort


@dataclass(frozen=True, slots=True)
class LoginUserResult:
    user_id: UUID
    tenant_id: UUID
    email: str
    is_superadmin: bool = False


async def login_user(
    *,
    users_repo: UserRepositoryPort,
    password_hasher: PasswordHasher,
    email: str,
    password: str,
) -> LoginUserResult:
    """Read-only: no writes, nothing to commit."""
    user = await users_repo.find_user_by_email(email)
    if user is None or user.password_hash is None:
        raise InvalidCredentialsError("Invalid email or password")
    if not password_hasher.verify(password, user.password_hash):
        raise InvalidCredentialsError("Invalid email or password")
    return LoginUserResult(
        user_id=user.id, tenant_id=user.tenant_id, email=user.email,
        is_superadmin=user.is_superadmin,
    )
