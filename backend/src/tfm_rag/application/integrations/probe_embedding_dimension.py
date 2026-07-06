"""Use-case: detect an embedding model's vector dimension by probing the endpoint.

Embeds one short probe text with the given (credential, model) and returns the
length of the returned vector = the true dimension. This removes the need for
the user to type the dimension by hand when creating a knowledge base, and is
authoritative (the real value from the provider, not a static catalog guess).

Never raises for upstream/provider failures — returns
``{"dim": None, "error": <message>}``. Only ``NotFoundError`` propagates
(bad/cross-tenant credential_id), which the router maps to HTTP 404.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.integrations.endpoint_resolver import resolve_inference_target
from tfm_rag.domain.ports.embedder import EmbedderDispatcherPort
from tfm_rag.infrastructure.persistence.repositories.credentials_repo import (
    ProviderCredentialRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext

_PROBE_TEXT = "dimension probe"


async def probe_embedding_dimension(
    session: AsyncSession,
    ctx: RequestContext,
    credential_id: UUID,
    model_id: str,
    *,
    dispatcher: EmbedderDispatcherPort,
    encryptor: Any,
    settings: Any,
) -> dict[str, Any]:
    """Return ``{"dim": int | None, "error": str | None}`` for (credential, model).

    Raises
    ------
    NotFoundError
        If the credential does not exist or belongs to a different tenant.
    """
    provider_id, base_url, api_key = await resolve_inference_target(
        credential_id=credential_id,
        credentials_repo=ProviderCredentialRepository(session, ctx),
        encryptor=encryptor,
        ollama_base_url=settings.ollama_base_url,
    )
    try:
        embedder = dispatcher.for_provider(provider_id)
        vectors = await embedder.embed(
            base_url=base_url, api_key=api_key, model_id=model_id,
            texts=[_PROBE_TEXT],
        )
    except Exception as exc:  # noqa: BLE001 — provider/network failure → error, not 5xx
        return {"dim": None, "error": str(exc)[:200]}
    if not vectors or not vectors[0]:
        return {"dim": None, "error": "the endpoint returned an empty embedding"}
    return {"dim": len(vectors[0]), "error": None}
