from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.integrations.delete_credential import delete_credential
from tfm_rag.application.integrations.list_credential_models import (
    list_credential_models,
)
from tfm_rag.application.integrations.list_credentials import (
    CredentialView,
    list_credentials,
)
from tfm_rag.application.integrations.probe_embedding_dimension import (
    probe_embedding_dimension,
)
from tfm_rag.application.integrations.test_credential import test_credential
from tfm_rag.application.integrations.upsert_provider_credential import (
    upsert_provider_credential,
)
from tfm_rag.domain.catalog.embedding_providers import (
    EMBEDDING_PROVIDER_CATALOG,
)
from tfm_rag.domain.catalog.llm_providers import (
    LLM_PROVIDER_CATALOG,
    LLMProviderDescriptor,
)
from tfm_rag.domain.errors.common import NotFoundError, ValidationError
from tfm_rag.domain.errors.integrations import CredentialNotFoundError
from tfm_rag.infrastructure.api.dependencies import (
    get_current_context,
    get_session,
)
from tfm_rag.infrastructure.embedders.dispatcher import EmbedderDispatcher
from tfm_rag.infrastructure.persistence.repositories.credentials_repo import (
    ProviderCredentialRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.secrets.fernet_encryptor import FernetSecretEncryptor
from tfm_rag.infrastructure.settings import Settings, get_settings

router = APIRouter(prefix="/api", tags=["integrations"])


class UpsertIn(BaseModel):
    provider_id: str
    label: str
    api_key: str
    base_url: str | None = None
    max_concurrency: int | None = None
    min_request_interval_seconds: float | None = None


class TestIn(BaseModel):
    model_id: str


class ModelEntry(BaseModel):
    id: str
    kind: str  # "llm" | "embedding" | "unknown"


class CredentialModelsOut(BaseModel):
    models: list[ModelEntry]
    error: str | None


class CredentialOut(BaseModel):
    id: str
    provider_id: str
    label: str
    base_url: str | None
    config_source: str
    max_concurrency: int | None = None
    min_request_interval_seconds: float | None = None

    @classmethod
    def from_view(cls, v: CredentialView) -> "CredentialOut":
        return cls(
            id=str(v.id),
            provider_id=v.provider_id,
            label=v.label,
            base_url=v.base_url,
            config_source=v.config_source,
            max_concurrency=v.max_concurrency,
            min_request_interval_seconds=v.min_request_interval_seconds,
        )


@router.get("/providers/llm")
async def list_llm_providers() -> list[LLMProviderDescriptor]:
    return list(LLM_PROVIDER_CATALOG.values())


@router.get("/providers/embedding")
async def list_embedding_providers() -> list[dict[str, object]]:
    return [
        {
            "id": d.id,
            "display_name": d.display_name,
            "description": d.description,
            "config_source": d.config_source,
            "requires_base_url_input": d.requires_base_url_input,
            "default_models": d.default_models,
        }
        for d in EMBEDDING_PROVIDER_CATALOG.values()
    ]


@router.get("/credentials")
async def list_(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> list[CredentialOut]:
    views = await list_credentials(
        credentials_repo=ProviderCredentialRepository(session, ctx)
    )
    return [CredentialOut.from_view(v) for v in views]


@router.post("/credentials", status_code=201)
async def create_(
    body: UpsertIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> CredentialOut:
    encryptor = FernetSecretEncryptor(settings.fernet_key)
    try:
        result = await upsert_provider_credential(
            credentials_repo=ProviderCredentialRepository(session, ctx),
            encryptor=encryptor,
            provider_id=body.provider_id,
            label=body.label,
            api_key=body.api_key,
            base_url=body.base_url,
            max_concurrency=body.max_concurrency,
            min_request_interval_seconds=body.min_request_interval_seconds,
        )
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return CredentialOut(
        id=str(result.id),
        provider_id=result.provider_id,
        label=result.label,
        base_url=body.base_url,
        config_source="TENANT_CREDENTIAL",
        max_concurrency=result.max_concurrency,
        min_request_interval_seconds=result.min_request_interval_seconds,
    )


@router.delete("/credentials/{credential_id}", status_code=204)
async def delete_(
    credential_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> None:
    try:
        await delete_credential(
            credentials_repo=ProviderCredentialRepository(session, ctx),
            credential_id=credential_id,
        )
    except NotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Credential not found"
        ) from None


@router.post("/credentials/{credential_id}/test")
async def test_(
    credential_id: UUID,
    body: TestIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> dict[str, object]:
    encryptor = FernetSecretEncryptor(settings.fernet_key)
    try:
        result = await test_credential(
            session,
            ctx,
            encryptor,
            credential_id=credential_id,
            model_id=body.model_id,
        )
    except CredentialNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return {
        "ok": result.ok,
        "latency_ms": result.latency_ms,
        "error": result.error,
    }


@router.get("/credentials/{credential_id}/models")
async def list_models_(
    credential_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> CredentialModelsOut:
    """Return the live model catalog for a saved credential.

    Response:
        {
          "models": [{"id": "...", "kind": "llm"|"embedding"|"unknown"}, ...],
          "error": null | "<message>"
        }

    Upstream failures (network, non-200, JSON errors) are returned as
    ``{"models": [], "error": "<message>"}`` with HTTP 200 — they are not
    propagated as 5xx.  A missing/cross-tenant credential_id → HTTP 404.
    """
    encryptor = FernetSecretEncryptor(settings.fernet_key)
    try:
        result = await list_credential_models(
            session,
            ctx,
            credential_id,
            encryptor=encryptor,
            settings=settings,
        )
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return CredentialModelsOut(
        models=[ModelEntry(id=m["id"], kind=m["kind"]) for m in result["models"]],
        error=result["error"],
    )


class EmbeddingDimensionOut(BaseModel):
    dim: int | None = None
    error: str | None = None


@router.get("/credentials/{credential_id}/embedding-dimension")
async def embedding_dimension_(
    credential_id: UUID,
    model: str,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> EmbeddingDimensionOut:
    """Auto-detect an embedding model's vector dimension by probing the endpoint
    (embeds a short text and measures the returned vector length).

    Upstream/provider failures are returned as ``{"dim": null, "error": "..."}``
    with HTTP 200; a missing/cross-tenant credential_id → HTTP 404.
    """
    encryptor = FernetSecretEncryptor(settings.fernet_key)
    try:
        result = await probe_embedding_dimension(
            session,
            ctx,
            credential_id,
            model,
            dispatcher=EmbedderDispatcher.default(),
            encryptor=encryptor,
            settings=settings,
        )
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return EmbeddingDimensionOut(dim=result["dim"], error=result["error"])
