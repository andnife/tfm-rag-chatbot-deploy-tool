from uuid import uuid4

import pytest

from tfm_rag.infrastructure.auth.jwt import (
    TokenInvalidError,
    decode_jwt,
    encode_jwt,
)


SECRET = "x" * 32


def test_encode_decode_roundtrip() -> None:
    user_id = uuid4()
    tenant_id = uuid4()
    token = encode_jwt(
        user_id=user_id, tenant_id=tenant_id, secret=SECRET, expires_hours=24
    )
    payload = decode_jwt(token, SECRET)
    assert payload["sub"] == str(user_id)
    assert payload["tid"] == str(tenant_id)
    assert payload["exp"] > payload["iat"]


def test_decode_with_wrong_secret_raises() -> None:
    token = encode_jwt(
        user_id=uuid4(), tenant_id=uuid4(), secret=SECRET, expires_hours=24
    )
    with pytest.raises(TokenInvalidError):
        decode_jwt(token, "y" * 32)


def test_decode_malformed_raises() -> None:
    with pytest.raises(TokenInvalidError):
        decode_jwt("not-a-jwt", SECRET)
