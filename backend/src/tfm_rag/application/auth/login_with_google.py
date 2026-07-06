from dataclasses import dataclass
from uuid import UUID, uuid4

from tfm_rag.application.auth.bootstrap_tenant import bootstrap_tenant
from tfm_rag.domain.errors.auth import InvalidCredentialsError
from tfm_rag.domain.ports.oauth_verifier import OAuthVerifier
from tfm_rag.domain.ports.repositories import (
    TenantRepositoryPort,
    UserRepositoryPort,
)


@dataclass(frozen=True, slots=True)
class LoginWithGoogleResult:
    user_id: UUID
    tenant_id: UUID
    email: str


async def login_with_google(
    *,
    users_repo: UserRepositoryPort,
    tenants_repo: TenantRepositoryPort,
    verifier: OAuthVerifier,
    google_id_token: str,
) -> LoginWithGoogleResult:
    """Commit contract: no commit here — link_google_sub, bootstrap_tenant
    and create_user all flush only; the router's session dependency commits
    at request end (rollback on exception), exactly as before the port
    migration.
    """
    profile = await verifier.verify(google_id_token)
    if not profile.email_verified:
        raise InvalidCredentialsError("Google account email is not verified")

    # 1. Try to find existing user by google_sub.
    user = await users_repo.find_user_by_google_sub(profile.sub)
    if user is not None:
        return LoginWithGoogleResult(
            user_id=user.id, tenant_id=user.tenant_id, email=user.email
        )

    # 2. If a user with this email exists (registered via password),
    #    link the google_sub instead of creating a duplicate.
    existing_by_email = await users_repo.find_user_by_email(profile.email)
    if existing_by_email is not None:
        if existing_by_email.google_sub is None:
            await users_repo.link_google_sub(existing_by_email.id, profile.sub)
        return LoginWithGoogleResult(
            user_id=existing_by_email.id,
            tenant_id=existing_by_email.tenant_id,
            email=existing_by_email.email,
        )

    # 3. First-time login → create user + tenant.
    bt = await bootstrap_tenant(tenants_repo=tenants_repo, name=profile.email)
    user_id = uuid4()
    await users_repo.create_user(
        user_id=user_id,
        email=profile.email,
        password_hash=None,
        google_sub=profile.sub,
        tenant_id=bt.tenant_id,
    )
    return LoginWithGoogleResult(
        user_id=user_id, tenant_id=bt.tenant_id, email=profile.email
    )
