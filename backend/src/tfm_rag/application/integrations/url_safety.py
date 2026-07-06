from ipaddress import ip_address
from urllib.parse import urlparse

from tfm_rag.domain.errors.common import ValidationError

_BLOCKED_NETWORKS = (
    "169.254.",     # AWS/GCP metadata
    "10.",          # RFC 1918
    "172.16.",      # RFC 1918
    "192.168.",     # RFC 1918
    "127.",         # loopback
    "0.",           # current network
    "localhost",
)


def normalize_base_url(url: str) -> str:
    """Canonicalize a base_url: trim surrounding whitespace and trailing slashes.

    Avoids double slashes when the URL is later joined with a path
    (e.g. ``/v1/`` + ``/chat/completions`` → ``/v1//chat/completions``).
    """
    return url.strip().rstrip("/")


def validate_base_url(url: str) -> None:
    """Reject URLs pointing to private networks or metadata endpoints (SSRF prevention)."""
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    for prefix in _BLOCKED_NETWORKS:
        if hostname.startswith(prefix) or hostname == prefix.rstrip("."):
            raise ValidationError(
                f"base_url points to a private network or metadata "
                f"endpoint; rejected: {url}"
            )
    # Reject decimal/hex/octal integer-encoded IPs (e.g. 2130706433 == 127.0.0.1,
    # 0x7f000001 == 127.0.0.1).  Python's ip_address() only accepts dotted/colon
    # forms, so these would otherwise slip through the check below.
    try:
        int_val = int(hostname, 0)
        addr = ip_address(int_val)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            raise ValidationError(
                f"base_url points to a private IP address; rejected: {url}"
            )
    except ValueError:
        pass  # Not an integer-encoded IP — fall through to dotted-form check
    try:
        addr = ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            raise ValidationError(
                f"base_url points to a private IP address; rejected: {url}"
            )
    except ValueError:
        pass  # Not an IP address, hostname-based check above is sufficient
