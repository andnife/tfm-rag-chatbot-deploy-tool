from typing import Literal

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings, get_settings
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore

router = APIRouter(tags=["health"])


class ComponentHealth(BaseModel):
    name: str
    status: Literal["ok", "fail"]
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    components: list[ComponentHealth]


@router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:  # noqa: B008
    components: list[ComponentHealth] = []

    # Postgres
    try:
        engine = build_engine(settings.postgres_url)
        factory = build_session_factory(engine)
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        await engine.dispose()
        components.append(ComponentHealth(name="postgres", status="ok"))
    except Exception as e:  # noqa: BLE001
        components.append(
            ComponentHealth(name="postgres", status="fail", detail=str(e)[:200])
        )

    # Qdrant
    qdrant = QdrantStore(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    try:
        ok = await qdrant.health()
        components.append(
            ComponentHealth(name="qdrant", status="ok" if ok else "fail")
        )
    finally:
        await qdrant.close()

    # Ollama
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{settings.ollama_base_url}/api/tags")
            r.raise_for_status()
        components.append(ComponentHealth(name="ollama", status="ok"))
    except Exception as e:  # noqa: BLE001
        components.append(
            ComponentHealth(name="ollama", status="fail", detail=str(e)[:200])
        )

    overall = "ok" if all(c.status == "ok" for c in components) else "degraded"
    return HealthResponse(status=overall, components=components)
