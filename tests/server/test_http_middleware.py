from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_request_size_limit_and_security_headers(tmp_path, isolated_app_factory):
    """Oversized requests are rejected and every response gets defensive headers."""
    app = isolated_app_factory(
        f"sqlite+pysqlite:///{tmp_path / 'middleware.db'}",
        max_request_body_bytes=1024,
    )
    with TestClient(app) as client:
        response = client.post(
            "/register",
            json={"email": "large@example.com", "password": "A" * 2000},
        )
        assert response.status_code == 413
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_streamed_body_is_limited_without_content_length() -> None:
    """Chunked bodies cannot bypass the request limit."""
    from riskapp_server.main.http_middleware import RequestBodyLimitMiddleware

    async def consume_body(scope, receive, send):
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    messages = iter(
        [
            {"type": "http.request", "body": b"1234", "more_body": True},
            {"type": "http.request", "body": b"56", "more_body": False},
        ]
    )
    sent = []

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    middleware = RequestBodyLimitMiddleware(consume_body, max_bytes=5)
    await middleware(
        {"type": "http", "method": "POST", "path": "/", "headers": []},
        receive,
        send,
    )

    assert sent[0]["status"] == 413
