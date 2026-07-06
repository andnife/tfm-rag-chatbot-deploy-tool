"""Unit tests for login_user use case."""
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from tfm_rag.application.auth.login_user import LoginUserResult, login_user
from tfm_rag.domain.entities.user import User
from tfm_rag.domain.errors.auth import InvalidCredentialsError

pytestmark = pytest.mark.asyncio

_NOW = datetime.now(UTC)


class _FakePasswordHasher:
    def __init__(self, *, verifies: bool) -> None:
        self._verifies = verifies
        self.calls: list[tuple[str, str]] = []

    def hash(self, password: str) -> str:
        return f"hash({password})"

    def verify(self, password: str, password_hash: str) -> bool:
        self.calls.append((password, password_hash))
        return self._verifies


class _FakeUsersRepo:
    def __init__(self, user: User | None) -> None:
        self._user = user
        self.lookups: list[str] = []

    async def find_user_by_email(self, email: str) -> User | None:
        self.lookups.append(email)
        return self._user


def _user(
    *,
    email: str = "user@example.com",
    password_hash: str | None = "hashed-pw",
    is_superadmin: bool = False,
) -> User:
    return User(
        id=uuid4(),
        email=email,
        password_hash=password_hash,
        google_sub=None,
        tenant_id=uuid4(),
        created_at=_NOW,
        updated_at=_NOW,
        is_superadmin=is_superadmin,
    )


async def test_login_success_returns_result() -> None:
    user = _user(is_superadmin=True)
    users_repo = _FakeUsersRepo(user)
    hasher = _FakePasswordHasher(verifies=True)

    result = await login_user(
        users_repo=users_repo,  # type: ignore[arg-type]
        password_hasher=hasher,  # type: ignore[arg-type]
        email=user.email,
        password="correct-password",
    )

    assert result == LoginUserResult(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        is_superadmin=True,
    )
    assert hasher.calls == [("correct-password", "hashed-pw")]
    assert users_repo.lookups == [user.email]


async def test_login_unknown_email_raises_invalid_credentials() -> None:
    users_repo = _FakeUsersRepo(None)
    hasher = _FakePasswordHasher(verifies=True)

    with pytest.raises(InvalidCredentialsError, match="Invalid email or password"):
        await login_user(
            users_repo=users_repo,  # type: ignore[arg-type]
            password_hasher=hasher,  # type: ignore[arg-type]
            email="nobody@example.com",
            password="whatever",
        )

    assert hasher.calls == []


async def test_login_google_only_account_has_no_password_hash_raises() -> None:
    """A user created via Google OAuth has password_hash=None; password login must fail."""
    user = _user(password_hash=None)
    users_repo = _FakeUsersRepo(user)
    hasher = _FakePasswordHasher(verifies=True)

    with pytest.raises(InvalidCredentialsError):
        await login_user(
            users_repo=users_repo,  # type: ignore[arg-type]
            password_hasher=hasher,  # type: ignore[arg-type]
            email=user.email,
            password="whatever",
        )

    assert hasher.calls == []


async def test_login_wrong_password_raises_invalid_credentials() -> None:
    user = _user()
    users_repo = _FakeUsersRepo(user)
    hasher = _FakePasswordHasher(verifies=False)

    with pytest.raises(InvalidCredentialsError):
        await login_user(
            users_repo=users_repo,  # type: ignore[arg-type]
            password_hasher=hasher,  # type: ignore[arg-type]
            email=user.email,
            password="wrong-password",
        )

    assert hasher.calls == [("wrong-password", "hashed-pw")]
