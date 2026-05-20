from dataclasses import dataclass
from time import perf_counter
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.domain.catalog.llm_providers import LLM_PROVIDER_CATALOG
from tfm_rag.domain.errors.integrations import CredentialNotFoundError
from tfm_rag.domain.ports.secret_encryptor import SecretEncryptor
from tfm_rag.infrastructure.persistence.repositories.credentials_repo import (
    ProviderCredentialRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext


@dataclass(frozen=True, slots=True)
class TestCredentialResult:
    ok: bool
    latency_ms: int
    error: str | None


async def test_credential(
    session: AsyncSession,
    ctx: RequestContext,
    encryptor: SecretEncryptor,
    *,
    credential_id: UUID,
    model_id: str,
) -> TestCredentialResult:
    repo = ProviderCredentialRepository(session, ctx)
    try:
        row = await repo.get(credential_id)
    except Exception as exc:
        raise CredentialNotFoundError(str(exc)) from exc

    descriptor = LLM_PROVIDER_CATALOG[row.provider_id]
    api_key = encryptor.decrypt(row.api_key_encrypted).decode("utf-8")
    base = row.base_url or "https://api.openai.com/v1"
    if descriptor.id == "openai":
        base = "https://api.openai.com/v1"

    started = perf_counter()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{base.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        latency = int((perf_counter() - started) * 1000)
        return TestCredentialResult(ok=False, latency_ms=latency, error=str(exc)[:200])
    latency = int((perf_counter() - started) * 1000)
    return TestCredentialResult(ok=True, latency_ms=latency, error=None)
