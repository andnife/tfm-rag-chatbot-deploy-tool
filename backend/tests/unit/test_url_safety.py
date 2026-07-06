import pytest

from tfm_rag.application.integrations.url_safety import (
    normalize_base_url,
    validate_base_url,
)
from tfm_rag.domain.errors.common import ValidationError


def test_public_https_url_is_accepted() -> None:
    validate_base_url("https://api.openai.com/v1")  # no raise


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000",
        "http://127.0.0.1/v1",
        "http://10.0.0.5/v1",
        "http://172.16.0.1/v1",
        "http://192.168.1.10",
        "http://169.254.169.254/latest/meta-data",
    ],
)
def test_private_and_metadata_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValidationError):
        validate_base_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://2130706433/v1",   # decimal encoding of 127.0.0.1
        "http://0x7f000001/",     # hex encoding of 127.0.0.1
    ],
)
def test_integer_encoded_loopback_ips_are_rejected(url: str) -> None:
    """Decimal/hex integer-encoded IPs that resolve to private addresses must be blocked."""
    with pytest.raises(ValidationError):
        validate_base_url(url)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://api.openai.com/v1/", "https://api.openai.com/v1"),
        ("https://api.openai.com/v1//", "https://api.openai.com/v1"),
        ("https://api.openai.com/", "https://api.openai.com"),
        ("https://api.openai.com/v1", "https://api.openai.com/v1"),
        ("  https://api.openai.com/v1/  ", "https://api.openai.com/v1"),
    ],
)
def test_normalize_base_url_strips_trailing_slashes_and_whitespace(
    raw: str, expected: str
) -> None:
    assert normalize_base_url(raw) == expected
