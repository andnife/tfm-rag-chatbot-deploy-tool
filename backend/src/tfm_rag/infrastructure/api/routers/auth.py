from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.auth.login_user import login_user
from tfm_rag.application.auth.login_with_google import login_with_google
from tfm_rag.application.auth.register_user import register_user
from tfm_rag.domain.errors.auth import (
    InvalidCredentialsError,
    UserAlreadyExistsError,
)
from tfm_rag.infrastructure.api.auth_cookie import (
    clear_auth_cookie,
    extract_token,
    set_auth_cookie,
)
from tfm_rag.infrastructure.api.dependencies import get_session
from tfm_rag.infrastructure.auth.google_oauth import GoogleOAuthVerifier
from tfm_rag.infrastructure.auth.jwt import TokenInvalidError, decode_jwt, encode_jwt
from tfm_rag.infrastructure.auth.password import BcryptPasswordHasher
from tfm_rag.infrastructure.persistence.models.users import UserRow
from tfm_rag.infrastructure.persistence.repositories.tenants_repo import (
    TenantProvisioningRepository,
)
from tfm_rag.infrastructure.persistence.repositories.users_repo import (
    UserRepository,
)
from tfm_rag.infrastructure.settings import Settings, get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class GoogleLoginIn(BaseModel):
    google_id_token: str


class AuthOut(BaseModel):
    user_id: str
    tenant_id: str
    email: str
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - literal token-type label, not a secret


def _token(
    *, user_id: Any, tenant_id: Any, is_superadmin: bool = False, settings: Settings
) -> str:
    return encode_jwt(
        user_id=user_id,
        tenant_id=tenant_id,
        secret=settings.jwt_secret,
        expires_hours=settings.jwt_expires_hours,
        is_superadmin=is_superadmin,
    )


@router.post("/register", response_model=AuthOut, status_code=201)
async def register(
    body: RegisterIn,
    response: Response,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AuthOut:
    try:
        result = await register_user(
            users_repo=UserRepository(session),
            tenants_repo=TenantProvisioningRepository(session),
            password_hasher=BcryptPasswordHasher(),
            email=body.email,
            password=body.password,
        )
    except UserAlreadyExistsError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Registration failed"
        ) from None
    token = _token(user_id=result.user_id, tenant_id=result.tenant_id, settings=settings)
    set_auth_cookie(
        response, token,
        secure=settings.cookie_secure,
        max_age=settings.jwt_expires_hours * 3600,
    )
    return AuthOut(
        user_id=str(result.user_id),
        tenant_id=str(result.tenant_id),
        email=result.email,
        access_token=token,
    )


@router.post("/login", response_model=AuthOut)
async def login(
    body: LoginIn,
    response: Response,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AuthOut:
    try:
        result = await login_user(
            users_repo=UserRepository(session),
            password_hasher=BcryptPasswordHasher(),
            email=body.email,
            password=body.password,
        )
    except InvalidCredentialsError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        ) from None
    token = _token(
        user_id=result.user_id, tenant_id=result.tenant_id,
        is_superadmin=result.is_superadmin, settings=settings,
    )
    set_auth_cookie(
        response, token,
        secure=settings.cookie_secure,
        max_age=settings.jwt_expires_hours * 3600,
    )
    return AuthOut(
        user_id=str(result.user_id),
        tenant_id=str(result.tenant_id),
        email=result.email,
        access_token=token,
    )


@router.post("/login/google", response_model=AuthOut)
async def login_google(
    body: GoogleLoginIn,
    response: Response,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AuthOut:
    if not settings.google_oauth_client_id:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth not configured",
        )
    verifier = GoogleOAuthVerifier(settings.google_oauth_client_id)
    try:
        result = await login_with_google(
            users_repo=UserRepository(session),
            tenants_repo=TenantProvisioningRepository(session),
            verifier=verifier,
            google_id_token=body.google_id_token,
        )
    except InvalidCredentialsError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Invalid Google credentials"
        ) from None
    token = _token(user_id=result.user_id, tenant_id=result.tenant_id, settings=settings)
    set_auth_cookie(
        response, token,
        secure=settings.cookie_secure,
        max_age=settings.jwt_expires_hours * 3600,
    )
    return AuthOut(
        user_id=str(result.user_id),
        tenant_id=str(result.tenant_id),
        email=result.email,
        access_token=token,
    )


@router.post("/logout", status_code=204)
async def logout(response: Response) -> None:
    """Clear the httpOnly auth cookie. Returns 204 No Content."""
    clear_auth_cookie(response)


class MeOut(BaseModel):
    id: str
    email: str
    tenant_id: str
    is_superadmin: bool = False


@router.get("/me", response_model=MeOut)
async def get_me(
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> MeOut:
    token = extract_token(request)
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    try:
        payload = decode_jwt(token, settings.jwt_secret)
    except TokenInvalidError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    user_id = payload["sub"]
    stmt = select(UserRow).where(UserRow.id == user_id)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")

    return MeOut(
        id=str(user.id),
        email=user.email,
        tenant_id=str(user.tenant_id),
        is_superadmin=bool(user.is_superadmin),
    )
