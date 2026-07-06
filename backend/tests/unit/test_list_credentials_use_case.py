"""Unit tests for list_credentials use case."""
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from tfm_rag.application.integrations.list_credentials import (
    CredentialView,
    list_credentials,
)
from tfm_rag.domain.entities.provider_credential import ProviderCredential

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)


def _credential(
    *,
    max_concurrency: int | None = None,
    min_request_interval_seconds: float | None = None,
) -> ProviderCredential:
    return ProviderCredential(
        id=uuid4(),
        tenant_id=uuid4(),
        provider_id="openai",
        label="default",
        api_key_encrypted=b"enc",
        base_url=None,
        config_source="TENANT_CREDENTIAL",  # type: ignore[arg-type]
        created_at=_NOW,
        updated_at=_NOW,
        max_concurrency=max_concurrency,
        min_request_interval_seconds=min_request_interval_seconds,
    )


class _FakeCredentialsRepo:
    def __init__(self, credentials: list[ProviderCredential]) -> None:
        self._credentials = credentials
        self.calls: list[dict] = []

    async def list_credentials(self, *, limit: int, offset: int) -> list[ProviderCredential]:
        self.calls.append({"limit": limit, "offset": offset})
        return self._credentials


async def test_list_credentials_maps_entities_to_view() -> None:
    cred = _credential(max_concurrency=5, min_request_interval_seconds=0.5)
    repo = _FakeCredentialsRepo([cred])

    result = await list_credentials(credentials_repo=repo)  # type: ignore[arg-type]

    assert result == [
        CredentialView(
            id=cred.id,
            provider_id="openai",
            label="default",
            base_url=None,
            config_source="TENANT_CREDENTIAL",
            created_at=_NOW,
            max_concurrency=5,
            min_request_interval_seconds=0.5,
        )
    ]


async def test_list_credentials_empty_repo_returns_empty_list() -> None:
    repo = _FakeCredentialsRepo([])

    result = await list_credentials(credentials_repo=repo)  # type: ignore[arg-type]

    assert result == []


async def test_list_credentials_requests_bounded_page() -> None:
    """The use case fixes the pagination window it asks the repo for."""
    repo = _FakeCredentialsRepo([])

    await list_credentials(credentials_repo=repo)  # type: ignore[arg-type]

    assert repo.calls == [{"limit": 200, "offset": 0}]


async def test_list_credentials_preserves_repo_order() -> None:
    creds = [_credential() for _ in range(3)]
    repo = _FakeCredentialsRepo(creds)

    result = await list_credentials(credentials_repo=repo)  # type: ignore[arg-type]

    assert [v.id for v in result] == [c.id for c in creds]
