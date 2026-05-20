from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.auth.bootstrap_tenant import bootstrap_tenant
from tfm_rag.domain.errors.auth import InvalidCredentialsError
from tfm_rag.domain.ports.oauth_verifier import OAuthVerifier
from tfm_rag.infrastructure.persistence.models.users import UserRow
from tfm_rag.infrastructure.persistence.repositories.users_repo import (
    UsersByEmailFinder,
)


@dataclass(frozen=True, slots=True)
class LoginWithGoogleResult:
    user_id: UUID
    tenant_id: UUID
    email: str


async def login_with_google(
    session: AsyncSession,
    verifier: OAuthVerifier,
    *,
    google_id_token: str,
) -> LoginWithGoogleResult:
    profile = await verifier.verify(google_id_token)
    if not profile.email_verified:
        raise InvalidCredentialsError("Google account email is not verified")

    finder = UsersByEmailFinder(session)
    user = await finder.find_by_google_sub(profile.sub)
    if user is None:
        # First-time login → create user + tenant
        bt = await bootstrap_tenant(session, name=profile.email)
        user_id = uuid4()
        new_user = UserRow(
            id=user_id,
            email=profile.email,
            password_hash=None,
            google_sub=profile.sub,
            tenant_id=bt.tenant_id,
        )
        session.add(new_user)
        await session.flush()
        return LoginWithGoogleResult(
            user_id=user_id, tenant_id=bt.tenant_id, email=profile.email
        )
    return LoginWithGoogleResult(
        user_id=user.id, tenant_id=user.tenant_id, email=user.email
    )
