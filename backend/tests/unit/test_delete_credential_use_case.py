"""Unit tests for delete_credential use case."""
from uuid import uuid4

import pytest

from tfm_rag.application.integrations.delete_credential import delete_credential

pytestmark = pytest.mark.asyncio


class _FakeCredentialsRepo:
    def __init__(self) -> None:
        self.deleted: list = []

    async def delete_credential(self, credential_id) -> None:  # type: ignore[no-untyped-def]
        self.deleted.append(credential_id)


async def test_delete_credential_delegates_to_repo() -> None:
    repo = _FakeCredentialsRepo()
    credential_id = uuid4()

    result = await delete_credential(
        credentials_repo=repo,  # type: ignore[arg-type]
        credential_id=credential_id,
    )

    assert result is None
    assert repo.deleted == [credential_id]


async def test_delete_credential_propagates_repo_errors() -> None:
    class _RaisingRepo:
        async def delete_credential(self, credential_id) -> None:  # type: ignore[no-untyped-def]
            raise RuntimeError("row not found")

    with pytest.raises(RuntimeError, match="row not found"):
        await delete_credential(
            credentials_repo=_RaisingRepo(),  # type: ignore[arg-type]
            credential_id=uuid4(),
        )
