from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.integrations.delete_credential import delete_credential
from tfm_rag.application.integrations.list_credentials import (
    CredentialView,
    list_credentials,
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
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.errors.integrations import CredentialNotFoundError
from tfm_rag.infrastructure.api.dependencies import (
    get_current_context,
    get_session,
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


class TestIn(BaseModel):
    model_id: str


class CredentialOut(BaseModel):
    id: str
    provider_id: str
    label: str
    base_url: str | None
    config_source: str

    @classmethod
    def from_view(cls, v: CredentialView) -> "CredentialOut":
        return cls(
            id=str(v.id),
            provider_id=v.provider_id,
            label=v.label,
            base_url=v.base_url,
            config_source=v.config_source,
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
    views = await list_credentials(session, ctx)
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
            session,
            ctx,
            encryptor,
            provider_id=body.provider_id,
            label=body.label,
            api_key=body.api_key,
            base_url=body.base_url,
        )
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return CredentialOut(
        id=str(result.id),
        provider_id=result.provider_id,
        label=result.label,
        base_url=body.base_url,
        config_source="TENANT_CREDENTIAL",
    )


@router.delete("/credentials/{credential_id}", status_code=204)
async def delete_(
    credential_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> None:
    try:
        await delete_credential(session, ctx, credential_id=credential_id)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


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
