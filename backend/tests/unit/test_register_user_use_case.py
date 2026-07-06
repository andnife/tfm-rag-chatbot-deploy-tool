"""Unit tests for register_user use case."""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from tfm_rag.application.auth.register_user import RegisterUserResult, register_user
from tfm_rag.domain.entities.user import User
from tfm_rag.domain.errors.auth import UserAlreadyExistsError

pytestmark = pytest.mark.asyncio

_NOW = datetime.now(UTC)


class _FakePasswordHasher:
    def hash(self, password: str) -> str:
        return f"hash({password})"

    def verify(self, password: str, password_hash: str) -> bool:
        raise NotImplementedError


class _FakeUsersRepo:
    def __init__(self, existing: User | None = None) -> None:
        self._existing = existing
        self.created: list[dict] = []

    async def find_user_by_email(self, email: str) -> User | None:
        return self._existing

    async def create_user(
        self,
        *,
        user_id,  # type: ignore[no-untyped-def]
        email: str,
        password_hash: str | None,
        google_sub: str | None,
        tenant_id,  # type: ignore[no-untyped-def]
    ) -> None:
        self.created.append(
            {
                "user_id": user_id,
                "email": email,
                "password_hash": password_hash,
                "google_sub": google_sub,
                "tenant_id": tenant_id,
            }
        )


async def test_register_new_user_bootstraps_tenant_and_creates_user() -> None:
    users_repo = _FakeUsersRepo(existing=None)
    tenants_repo = object()
    tenant_id = uuid4()

    bootstrap_result = AsyncMock()
    bootstrap_result.tenant_id = tenant_id

    with patch(
        "tfm_rag.application.auth.register_user.bootstrap_tenant",
        new=AsyncMock(return_value=bootstrap_result),
    ) as bootstrap_mock:
        result = await register_user(
            users_repo=users_repo,  # type: ignore[arg-type]
            tenants_repo=tenants_repo,  # type: ignore[arg-type]
            password_hasher=_FakePasswordHasher(),  # type: ignore[arg-type]
            email="new@example.com",
            password="s3cret-pw",
        )

    assert isinstance(result, RegisterUserResult)
    assert result.email == "new@example.com"
    assert result.tenant_id == tenant_id
    assert result.is_superadmin is False

    bootstrap_mock.assert_awaited_once_with(
        tenants_repo=tenants_repo, name="new@example.com"
    )

    assert len(users_repo.created) == 1
    created = users_repo.created[0]
    assert created["user_id"] == result.user_id
    assert created["email"] == "new@example.com"
    assert created["password_hash"] == "hash(s3cret-pw)"
    assert created["google_sub"] is None
    assert created["tenant_id"] == tenant_id


async def test_register_existing_email_raises_without_bootstrapping() -> None:
    existing = User(
        id=uuid4(),
        email="taken@example.com",
        password_hash="hash",
        google_sub=None,
        tenant_id=uuid4(),
        created_at=_NOW,
        updated_at=_NOW,
    )
    users_repo = _FakeUsersRepo(existing=existing)

    with patch(
        "tfm_rag.application.auth.register_user.bootstrap_tenant",
        new=AsyncMock(),
    ) as bootstrap_mock, pytest.raises(
        UserAlreadyExistsError, match="taken@example.com"
    ):
        await register_user(
            users_repo=users_repo,  # type: ignore[arg-type]
            tenants_repo=object(),  # type: ignore[arg-type]
            password_hasher=_FakePasswordHasher(),  # type: ignore[arg-type]
            email="taken@example.com",
            password="whatever",
        )

    bootstrap_mock.assert_not_called()
    assert users_repo.created == []
