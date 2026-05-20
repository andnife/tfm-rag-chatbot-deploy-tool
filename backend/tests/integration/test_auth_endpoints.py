import pytest
from httpx import ASGITransport, AsyncClient

from tfm_rag.infrastructure.api.app import app


@pytest.mark.integration
async def test_register_then_login_then_me_flow() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register a fresh user
        reg = await client.post(
            "/api/auth/register",
            json={"email": "alice@example.com", "password": "correctpassword"},
        )
        assert reg.status_code == 201, reg.text
        reg_body = reg.json()
        assert reg_body["email"] == "alice@example.com"
        assert reg_body["token"]

        # Login with the same credentials
        login = await client.post(
            "/api/auth/login",
            json={"email": "alice@example.com", "password": "correctpassword"},
        )
        assert login.status_code == 200, login.text
        assert login.json()["user_id"] == reg_body["user_id"]

        # Wrong password
        bad = await client.post(
            "/api/auth/login",
            json={"email": "alice@example.com", "password": "wrong"},
        )
        assert bad.status_code == 401

        # Duplicate register
        dup = await client.post(
            "/api/auth/register",
            json={"email": "alice@example.com", "password": "x"},
        )
        assert dup.status_code == 409
