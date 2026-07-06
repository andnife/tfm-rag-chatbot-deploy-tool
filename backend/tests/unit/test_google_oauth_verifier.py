"""Unit tests for infrastructure/auth/google_oauth.py (GoogleOAuthVerifier).

Mocks the Google client library (`google.oauth2.id_token.verify_oauth2_token`)
so no real network/Google call happens.
"""
from unittest.mock import patch

import pytest

from tfm_rag.domain.errors.auth import InvalidCredentialsError
from tfm_rag.domain.ports.oauth_verifier import OAuthProfile
from tfm_rag.infrastructure.auth.google_oauth import GoogleOAuthVerifier

pytestmark = pytest.mark.asyncio


async def test_verify_valid_token_returns_profile() -> None:
    verifier = GoogleOAuthVerifier(client_id="client-123.apps.googleusercontent.com")

    with patch(
        "tfm_rag.infrastructure.auth.google_oauth.google_id_token.verify_oauth2_token",
        return_value={
            "sub": "1234567890",
            "email": "user@example.com",
            "email_verified": True,
        },
    ) as mock_verify:
        profile = await verifier.verify("valid-id-token")

    assert profile == OAuthProfile(
        sub="1234567890", email="user@example.com", email_verified=True
    )
    args, _ = mock_verify.call_args
    assert args[0] == "valid-id-token"
    assert args[2] == "client-123.apps.googleusercontent.com"


async def test_verify_missing_email_defaults_to_empty_unverified() -> None:
    verifier = GoogleOAuthVerifier(client_id="client-123")

    with patch(
        "tfm_rag.infrastructure.auth.google_oauth.google_id_token.verify_oauth2_token",
        return_value={"sub": "999"},
    ):
        profile = await verifier.verify("some-token")

    assert profile.sub == "999"
    assert profile.email == ""
    assert profile.email_verified is False


async def test_verify_invalid_token_raises_invalid_credentials() -> None:
    verifier = GoogleOAuthVerifier(client_id="client-123")

    with patch(
        "tfm_rag.infrastructure.auth.google_oauth.google_id_token.verify_oauth2_token",
        side_effect=ValueError("Token used too late"),
    ), pytest.raises(InvalidCredentialsError, match="Token used too late"):
        await verifier.verify("expired-token")
