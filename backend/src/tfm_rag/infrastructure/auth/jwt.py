from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from jose import JWTError, jwt

from tfm_rag.domain.errors.common import DomainError


class TokenInvalidError(DomainError):
    """Raised when a JWT is missing, malformed, or expired."""


def encode_jwt(
    *,
    user_id: UUID,
    tenant_id: UUID,
    secret: str,
    expires_hours: int,
) -> str:
    """Create a signed JWT (HS256) carrying user_id and tenant_id."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=expires_hours)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_jwt(token: str, secret: str) -> dict[str, Any]:
    """Verify signature + expiration. Returns the payload dict.

    Raises TokenInvalidError on any failure (expired, bad signature, malformed).
    """
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except JWTError as exc:
        raise TokenInvalidError(str(exc)) from exc
