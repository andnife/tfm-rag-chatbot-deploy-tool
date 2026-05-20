import pytest
from httpx import ASGITransport, AsyncClient

from tfm_rag.infrastructure.api.app import app


@pytest.mark.integration
async def test_health_returns_ok_when_stack_up() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ok", "degraded"}
    names = {c["name"] for c in body["components"]}
    assert names == {"postgres", "qdrant", "ollama"}
