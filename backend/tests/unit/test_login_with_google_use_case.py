"""Unit tests for login_with_google use case."""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from tfm_rag.application.auth.login_with_google import (
    LoginWithGoogleResult,
    login_with_google,
)
from tfm_rag.domain.entities.user import User
from tfm_rag.domain.errors.auth import InvalidCredentialsError
from tfm_rag.domain.ports.oauth_verifier import OAuthProfile, OAuthVerifier

_NOW = datetime.now(UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    sub: str = "google-sub-123",
    email: str = "user@example.com",
    email_verified: bool = True,
) -> OAuthProfile:
    return OAuthProfile(sub=sub, email=email, email_verified=email_verified)


def _make_verifier(profile: OAuthProfile) -> OAuthVerifier:
    verifier = MagicMock(spec=OAuthVerifier)
    verifier.verify = AsyncMock(return_value=profile)
    return verifier


def _make_user(
    email: str = "user@example.com",
    google_sub: str | None = "google-sub-123",
) -> User:
    return User(
        id=uuid4(),
        email=email,
        password_hash=None if google_sub else "hash",
        google_sub=google_sub,
        tenant_id=uuid4(),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_users_repo(
    by_google_sub: User | None = None,
    by_email: User | None = None,
) -> MagicMock:
    repo = MagicMock()
    repo.find_user_by_google_sub = AsyncMock(return_value=by_google_sub)
    repo.find_user_by_email = AsyncMock(return_value=by_email)
    repo.link_google_sub = AsyncMock()
    repo.create_user = AsyncMock()
    return repo


# ---------------------------------------------------------------------------
# Happy path: existing user found by google_sub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_existing_user_by_google_sub() -> None:
    """When a user already has this google_sub, return their IDs immediately."""
    existing_user = _make_user()
    profile = _make_profile(
        sub=existing_user.google_sub or "", email=existing_user.email
    )
    verifier = _make_verifier(profile)
    users_repo = _make_users_repo(by_google_sub=existing_user)
    tenants_repo = MagicMock()

    result = await login_with_google(
        users_repo=users_repo, tenants_repo=tenants_repo,
        verifier=verifier, google_id_token="tok",
    )

    assert isinstance(result, LoginWithGoogleResult)
    assert result.user_id == existing_user.id
    assert result.tenant_id == existing_user.tenant_id
    assert result.email == existing_user.email

    verifier.verify.assert_called_once_with("tok")
    # find_user_by_google_sub was the first (and only needed) lookup
    users_repo.find_user_by_google_sub.assert_awaited_once()
    users_repo.find_user_by_email.assert_not_called()


# ---------------------------------------------------------------------------
# Happy path: new user (first-time Google login) — creates user + tenant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_new_user_creates_tenant_and_user() -> None:
    """First-time Google login: no existing user by sub or email → bootstrap tenant."""
    profile = _make_profile(sub="new-sub-999", email="newuser@example.com")
    verifier = _make_verifier(profile)
    users_repo = _make_users_repo(by_google_sub=None, by_email=None)
    tenants_repo = MagicMock()

    tenant_id = uuid4()
    bootstrap_result = MagicMock()
    bootstrap_result.tenant_id = tenant_id

    with patch(
        "tfm_rag.application.auth.login_with_google.bootstrap_tenant",
        new=AsyncMock(return_value=bootstrap_result),
    ) as bootstrap_mock:
        result = await login_with_google(
            users_repo=users_repo, tenants_repo=tenants_repo,
            verifier=verifier, google_id_token="tok",
        )

    assert isinstance(result, LoginWithGoogleResult)
    assert result.tenant_id == tenant_id
    assert result.email == "newuser@example.com"
    assert result.user_id is not None

    bootstrap_mock.assert_awaited_once_with(
        tenants_repo=tenants_repo, name="newuser@example.com"
    )

    # New user persisted through the port
    users_repo.create_user.assert_awaited_once()
    kwargs = users_repo.create_user.call_args.kwargs
    assert kwargs["email"] == "newuser@example.com"
    assert kwargs["google_sub"] == "new-sub-999"
    assert kwargs["password_hash"] is None
    assert kwargs["tenant_id"] == tenant_id
    assert kwargs["user_id"] == result.user_id


# ---------------------------------------------------------------------------
# Email-linked account: existing user found by email (no google_sub yet)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_links_google_sub_to_existing_email_account() -> None:
    """User registered via password; first Google login links the google_sub."""
    existing_user = _make_user(google_sub=None)  # password-only account
    profile = _make_profile(sub="new-sub-for-email-user", email=existing_user.email)
    verifier = _make_verifier(profile)
    users_repo = _make_users_repo(by_google_sub=None, by_email=existing_user)
    tenants_repo = MagicMock()

    result = await login_with_google(
        users_repo=users_repo, tenants_repo=tenants_repo,
        verifier=verifier, google_id_token="tok",
    )

    assert result.user_id == existing_user.id
    assert result.tenant_id == existing_user.tenant_id
    assert result.email == existing_user.email

    # google_sub was linked onto the existing account (flush-only port write)
    users_repo.link_google_sub.assert_awaited_once_with(
        existing_user.id, "new-sub-for-email-user"
    )
    users_repo.create_user.assert_not_called()


# ---------------------------------------------------------------------------
# Email-linked account: google_sub already set — no extra write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_email_match_sub_already_set_no_extra_write() -> None:
    """If the email-matched user already has a google_sub set, skip the link."""
    existing_user = _make_user(google_sub="already-set-sub")
    profile = _make_profile(sub="already-set-sub", email=existing_user.email)
    verifier = _make_verifier(profile)
    # find_user_by_google_sub returns None (different sub stored), but email hits
    users_repo = _make_users_repo(by_google_sub=None, by_email=existing_user)
    tenants_repo = MagicMock()

    result = await login_with_google(
        users_repo=users_repo, tenants_repo=tenants_repo,
        verifier=verifier, google_id_token="tok",
    )

    assert result.user_id == existing_user.id
    # No write — google_sub was already populated
    users_repo.link_google_sub.assert_not_called()
    users_repo.create_user.assert_not_called()


# ---------------------------------------------------------------------------
# Error: email_verified is False → raises InvalidCredentialsError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_unverified_email_raises() -> None:
    """Google profile with email_verified=False must raise InvalidCredentialsError."""
    profile = _make_profile(email_verified=False)
    verifier = _make_verifier(profile)
    users_repo = _make_users_repo()
    tenants_repo = MagicMock()

    with pytest.raises(InvalidCredentialsError, match="not verified"):
        await login_with_google(
            users_repo=users_repo, tenants_repo=tenants_repo,
            verifier=verifier, google_id_token="bad-tok",
        )

    # No repo lookups issued
    users_repo.find_user_by_google_sub.assert_not_called()
    users_repo.find_user_by_email.assert_not_called()


# ---------------------------------------------------------------------------
# Error: verifier raises (invalid/expired token)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_invalid_token_raises() -> None:
    """If the OAuthVerifier raises, the exception propagates unchanged."""
    verifier = MagicMock(spec=OAuthVerifier)
    verifier.verify = AsyncMock(side_effect=ValueError("Token expired"))
    users_repo = _make_users_repo()
    tenants_repo = MagicMock()

    with pytest.raises(ValueError, match="Token expired"):
        await login_with_google(
            users_repo=users_repo, tenants_repo=tenants_repo,
            verifier=verifier, google_id_token="expired-tok",
        )

    users_repo.find_user_by_google_sub.assert_not_called()
