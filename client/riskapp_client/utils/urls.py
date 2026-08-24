"""URL helpers."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class UrlPolicy:
    """Base URL rules."""

    allow_http_localhost: bool = True
    allow_http_anywhere: bool = False


def validate_base_url(base_url: str, policy: UrlPolicy) -> str:
    """Return a normalized backend URL."""
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise ValueError("base_url must not be empty")
    if any(ch.isspace() for ch in url):
        raise ValueError("base_url must not contain whitespace")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("base_url must start with http:// or https://")
    if not parsed.netloc:
        raise ValueError("base_url must include a host (e.g. https://example.com)")
    if parsed.username or parsed.password:
        raise ValueError("base_url must not include embedded credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url must not include a query or fragment")
    host = (parsed.hostname or "").lower()
    is_local = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme == "http":
        if policy.allow_http_anywhere:
            return url
        if policy.allow_http_localhost and is_local:
            return url
        raise ValueError("http:// URL is not allowed")
    return url
