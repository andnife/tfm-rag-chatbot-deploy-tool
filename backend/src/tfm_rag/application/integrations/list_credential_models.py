"""Use-case: list available models for a saved provider credential.

Delegates to the provider adapter's ``list_models`` port (via
``LLMDispatcher``).  Endpoint resolution is handled by
``resolve_inference_target``, which is tenant-scoped.

Never raises for upstream failures — those are returned as
``{"models": [], "error": <message>}``.  Only ``NotFoundError`` propagates
(bad/cross-tenant credential_id).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.integrations.endpoint_resolver import resolve_inference_target
from tfm_rag.domain.errors.chat import LLMError
from tfm_rag.infrastructure.llm_providers.dispatcher import LLMDispatcher
from tfm_rag.infrastructure.persistence.repositories.credentials_repo import (
    ProviderCredentialRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext


async def list_credential_models(
    session: AsyncSession,
    ctx: RequestContext,
    credential_id: UUID,
    *,
    encryptor: Any,
    settings: Any,
) -> dict[str, Any]:
    """Return ``{"models": [...], "error": str | None}`` for *credential_id*.

    Each model entry is ``{"id": str, "kind": "llm" | "embedding" | "unknown"}``.

    Parameters
    ----------
    session:
        SQLAlchemy async session (passed straight to the repo).
    ctx:
        Tenant-scoped request context.
    credential_id:
        UUID of the saved credential to inspect.
    encryptor:
        Secret encryptor used to decrypt the API key.
    settings:
        Application settings (provides ``ollama_base_url``).

    Raises
    ------
    NotFoundError
        If the credential does not exist or belongs to a different tenant.
    """
    # resolve_inference_target fetches the credential row (tenant-scoped) and
    # derives (provider_id, base_url, api_key).  NotFoundError propagates
    # unchanged — the router maps it to HTTP 404.
    provider_id, base_url, api_key = await resolve_inference_target(
        credential_id=credential_id,
        credentials_repo=ProviderCredentialRepository(session, ctx),
        encryptor=encryptor,
        ollama_base_url=settings.ollama_base_url,
    )

    adapter = LLMDispatcher.default().for_provider(provider_id)

    try:
        models = await adapter.list_models(base_url=base_url, api_key=api_key)
        return {"models": models, "error": None}
    except LLMError as exc:
        return {"models": [], "error": str(exc)[:200]}
