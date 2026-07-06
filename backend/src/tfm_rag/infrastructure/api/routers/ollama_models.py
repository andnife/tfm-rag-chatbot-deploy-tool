"""Endpoint to list actually available Ollama models (pulled locally)."""

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from tfm_rag.infrastructure.settings import Settings, get_settings

router = APIRouter(prefix="/api/ollama", tags=["ollama"])


@router.get("/models")
async def list_ollama_models(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> dict[str, Any]:
    """Return the list of models actually available on the Ollama server.

    Response:
        {
          "models": [
            { "name": "llama3.1:latest", "size": 4900000000, "parameter_size": "8B" },
            ...
          ]
        }
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{settings.ollama_base_url}/api/tags")
            r.raise_for_status()
            data = r.json()
    except httpx.ConnectError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo conectar con Ollama. Verifica que esté ejecutándose.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al consultar Ollama: {exc}",
        ) from exc

    models = []
    for m in data.get("models", []):
        models.append({
            "name": m.get("name", ""),
            "size": m.get("size", 0),
            "digest": m.get("digest", ""),
            "modified_at": m.get("modified_at", ""),
            "details": m.get("details", {}),
        })

    return {"models": models}
