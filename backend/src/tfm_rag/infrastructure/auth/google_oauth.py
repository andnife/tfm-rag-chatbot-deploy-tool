import asyncio
from typing import Any

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from tfm_rag.domain.errors.auth import InvalidCredentialsError
from tfm_rag.domain.ports.oauth_verifier import OAuthProfile, OAuthVerifier


class GoogleOAuthVerifier(OAuthVerifier):
    def __init__(self, client_id: str) -> None:
        self._client_id = client_id
        self._req = google_requests.Request()

    async def verify(self, id_token: str) -> OAuthProfile:
        try:
            info: dict[str, Any] = await asyncio.to_thread(
                google_id_token.verify_oauth2_token,
                id_token,
                self._req,
                self._client_id,
            )
        except ValueError as exc:
            raise InvalidCredentialsError(f"Invalid Google id_token: {exc}") from exc
        return OAuthProfile(
            sub=str(info["sub"]),
            email=str(info.get("email", "")),
            email_verified=bool(info.get("email_verified", False)),
        )
