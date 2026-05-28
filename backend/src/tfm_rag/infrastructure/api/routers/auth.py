from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.auth.login_user import login_user
from tfm_rag.application.auth.login_with_google import login_with_google
from tfm_rag.application.auth.register_user import register_user
from tfm_rag.domain.errors.auth import (
    InvalidCredentialsError,
    UserAlreadyExistsError,
)
from tfm_rag.infrastructure.api.dependencies import get_session
from tfm_rag.infrastructure.auth.google_oauth import GoogleOAuthVerifier
from tfm_rag.infrastructure.auth.jwt import encode_jwt
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
    token: str


def _token(*, user_id: Any, tenant_id: Any, settings: Settings) -> str:
    return encode_jwt(
        user_id=user_id,
        tenant_id=tenant_id,
        secret=settings.jwt_secret,
        expires_hours=settings.jwt_expires_hours,
    )


@router.post("/register", response_model=AuthOut, status_code=201)
async def register(
    body: RegisterIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AuthOut:
    try:
        result = await register_user(
            session, email=body.email, password=body.password
        )
    except UserAlreadyExistsError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Registration failed"
        ) from None
    return AuthOut(
        user_id=str(result.user_id),
        tenant_id=str(result.tenant_id),
        email=result.email,
        token=_token(
            user_id=result.user_id, tenant_id=result.tenant_id, settings=settings
        ),
    )


@router.post("/login", response_model=AuthOut)
async def login(
    body: LoginIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AuthOut:
    try:
        result = await login_user(
            session, email=body.email, password=body.password
        )
    except InvalidCredentialsError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        ) from None
    return AuthOut(
        user_id=str(result.user_id),
        tenant_id=str(result.tenant_id),
        email=result.email,
        token=_token(
            user_id=result.user_id, tenant_id=result.tenant_id, settings=settings
        ),
    )


@router.post("/login/google", response_model=AuthOut)
async def login_google(
    body: GoogleLoginIn,
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
            session, verifier, google_id_token=body.google_id_token
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    return AuthOut(
        user_id=str(result.user_id),
        tenant_id=str(result.tenant_id),
        email=result.email,
        token=_token(
            user_id=result.user_id, tenant_id=result.tenant_id, settings=settings
        ),
    )
