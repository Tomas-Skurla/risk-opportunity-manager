"""Backend URL validation policy."""

from __future__ import annotations

import pytest
from riskapp_client.utils.urls import UrlPolicy, validate_base_url


def test_validate_base_url_accepts_https_and_localhost_http() -> None:
    """HTTPS is accepted; HTTP requires localhost by default."""


    policy = UrlPolicy()  # allow_http_localhost=True, allow_http_anywhere=False

    assert (
        validate_base_url("https://api.example.com", policy)
        == "https://api.example.com"
    )
    assert (
        validate_base_url("http://localhost:8000/", policy) == "http://localhost:8000"
    )
    assert validate_base_url("http://127.0.0.1:8000", policy) == "http://127.0.0.1:8000"

    # Plain http to a non-localhost host is rejected unless explicitly allowed.
    with pytest.raises(ValueError):
        validate_base_url("http://example.com", policy)

    # When http everywhere is allowed, the same URL goes through.
    permissive = UrlPolicy(allow_http_anywhere=True)
    assert validate_base_url("http://example.com", permissive) == "http://example.com"


def test_validate_base_url_rejects_credentials_query_whitespace_and_bad_scheme() -> (
    None
):
    """Reject malformed URLs, credentials, queries and fragments."""


    policy = UrlPolicy()
    bad_urls = [
        "",
        "   ",
        "https://example .com",  # whitespace
        "ftp://example.com",  # bad scheme
        "://example.com",  # missing scheme
        "https://user:pw@example.com",  # embedded credentials
        "https://example.com?x=1",  # query
        "https://example.com#frag",  # fragment
    ]
    for url in bad_urls:
        with pytest.raises(ValueError):
            validate_base_url(url, policy)
