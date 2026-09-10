from __future__ import annotations

import json
import logging

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
        assert response.headers["x-request-id"]


def test_request_id_is_preserved_and_available_to_application_logs(
    tmp_path, isolated_app_factory
) -> None:
    from riskapp_server.core.logging_config import request_id

    app = isolated_app_factory(
        f"sqlite+pysqlite:///{tmp_path / 'request-id.db'}"
    )

    @app.get("/_request-id-test")
    def request_id_test():
        return {"request_id": request_id()}

    supplied = "portfolio-test.request-42"
    with TestClient(app) as client:
        response = client.get(
            "/_request-id-test?do-not-log=this",
            headers={"X-Request-ID": supplied},
        )

    assert response.status_code == 200
    assert response.json() == {"request_id": supplied}
    assert response.headers["x-request-id"] == supplied
    assert request_id() == "-"


def test_invalid_request_id_is_replaced(tmp_path, isolated_app_factory) -> None:
    app = isolated_app_factory(
        f"sqlite+pysqlite:///{tmp_path / 'invalid-request-id.db'}"
    )
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": "bad id"})

    generated = response.headers["x-request-id"]
    assert generated != "bad id"
    assert len(generated) == 36


def test_unhandled_error_response_keeps_request_id(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(
        f"sqlite+pysqlite:///{tmp_path / 'error-request-id.db'}"
    )

    @app.get("/_unhandled-error-test")
    def unhandled_error_test():
        raise RuntimeError("private failure detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/_unhandled-error-test",
            headers={"X-Request-ID": "request-on-error"},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert response.headers["x-request-id"] == "request-on-error"
    assert "private failure detail" not in response.text


def test_json_log_formatter_emits_bounded_structured_fields() -> None:
    from riskapp_server.core.logging_config import JsonFormatter

    record = logging.makeLogRecord(
        {
            "name": "riskapp_server.request",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "pathname": __file__,
            "lineno": 1,
            "msg": "HTTP request %s",
            "args": ("completed",),
            "request_id": "request-7",
            "http_method": "GET",
            "http_path": "/health",
            "http_status": 200,
            "duration_ms": 1.25,
            "authorization": "must-not-leak",
        }
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "HTTP request completed"
    assert payload["request_id"] == "request-7"
    assert payload["http_method"] == "GET"
    assert payload["http_path"] == "/health"
    assert payload["http_status"] == 200
    assert payload["duration_ms"] == 1.25
    assert "authorization" not in payload


def test_plain_log_formatter_includes_request_fields() -> None:
    from riskapp_server.core.logging_config import UtcPlainFormatter

    record = logging.makeLogRecord(
        {
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "HTTP request completed",
            "request_id": "request-8",
            "http_method": "GET",
            "http_path": "/health",
            "http_status": 200,
            "duration_ms": 1.5,
        }
    )

    rendered = UtcPlainFormatter(
        "%(message)s request_id=%(request_id)s"
    ).format(record)

    assert "request_id=request-8" in rendered
    assert 'method="GET"' in rendered
    assert 'path="/health"' in rendered
    assert "status=200" in rendered
    assert "duration_ms=1.5" in rendered


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
