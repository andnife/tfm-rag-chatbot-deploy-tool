"""Regression: updating a provider credential must not raise MissingGreenlet.

`provider_credentials.updated_at` carries a SQL-side `onupdate=func.now()`, so
after an UPDATE its ORM attribute is expired (SQLAlchemy can't know the
DB-computed timestamp) even though the session uses expire_on_commit=False.
`ProviderCredentialRepository.update_credential` then builds the domain entity
by reading every column, including `updated_at` — which previously triggered a
lazy, *synchronous* reload against the async pool and raised
`sqlalchemy.exc.MissingGreenlet`. The repo now awaits `session.refresh(row)`
after commit so the reload happens in the async context.
"""
from uuid import uuid4

import pytest

from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.persistence.models.tenants import TenantRow
from tfm_rag.infrastructure.persistence.repositories.credentials_repo import (
    ProviderCredentialRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.settings import Settings


async def _make_tenant(factory, tenant_id) -> None:
    async with factory() as s:
        s.add(
            TenantRow(
                id=tenant_id,
                name=f"t-{tenant_id}",
                qdrant_collection_prefix=f"kb_chunks__{tenant_id}",
                storage_prefix=f"tenant_{tenant_id}/",
            )
        )
        await s.commit()


@pytest.mark.integration
async def test_update_credential_does_not_raise_missing_greenlet(
    settings: Settings,
) -> None:
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    ctx = RequestContext(tenant_id=uuid4(), user_id=uuid4())
    await _make_tenant(factory, ctx.tenant_id)

    async with factory() as s:
        repo = ProviderCredentialRepository(s, ctx)
        created = await repo.create_credential(
            provider_id="deepinfra",
            label=f"lbl-{uuid4().hex[:8]}",
            api_key_encrypted=b"old-key",
            base_url="https://api.deepinfra.com/v1/openai",
            max_concurrency=None,
            min_request_interval_seconds=None,
        )

    # The update path: previously raised MissingGreenlet on reading updated_at.
    async with factory() as s:
        repo = ProviderCredentialRepository(s, ctx)
        updated = await repo.update_credential(
            created.id,
            api_key_encrypted=b"new-key",
            base_url="https://api.deepinfra.com/v1/openai",
            max_concurrency=4,
            min_request_interval_seconds=2.0,
        )

    assert updated.id == created.id
    assert updated.api_key_encrypted == b"new-key"
    assert updated.max_concurrency == 4
    # Reading updated_at is exactly what used to blow up — assert it's populated
    # and moved forward relative to created_at.
    assert updated.updated_at is not None
    assert updated.updated_at >= created.created_at

    await engine.dispose()
