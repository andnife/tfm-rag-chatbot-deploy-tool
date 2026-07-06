from dataclasses import dataclass
from uuid import UUID, uuid4

from tfm_rag.application.auth.bootstrap_tenant import bootstrap_tenant
from tfm_rag.domain.errors.auth import UserAlreadyExistsError
from tfm_rag.domain.ports.password_hasher import PasswordHasher
from tfm_rag.domain.ports.repositories import (
    TenantRepositoryPort,
    UserRepositoryPort,
)


@dataclass(frozen=True, slots=True)
class RegisterUserResult:
    user_id: UUID
    tenant_id: UUID
    email: str
    is_superadmin: bool = False


async def register_user(
    *,
    users_repo: UserRepositoryPort,
    tenants_repo: TenantRepositoryPort,
    password_hasher: PasswordHasher,
    email: str,
    password: str,
) -> RegisterUserResult:
    """Commit contract: no commit here — bootstrap_tenant and create_user
    both flush only; the router's session dependency commits the whole
    user+tenant+credential unit of work atomically at request end (and
    rolls back on exception), exactly as before the port migration.
    """
    if await users_repo.find_user_by_email(email) is not None:
        raise UserAlreadyExistsError(f"Email {email} already registered")

    bt = await bootstrap_tenant(tenants_repo=tenants_repo, name=email)

    user_id = uuid4()
    await users_repo.create_user(
        user_id=user_id,
        email=email,
        password_hash=password_hasher.hash(password),
        google_sub=None,
        tenant_id=bt.tenant_id,
    )
    return RegisterUserResult(
        user_id=user_id, tenant_id=bt.tenant_id, email=email
    )
