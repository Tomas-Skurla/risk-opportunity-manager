"""Small ASGI middleware used by the API boundary."""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from riskapp_server.core.logging_config import bind_request_id, reset_request_id

_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_REQUEST_LOGGER = logging.getLogger("riskapp_server.request")


def _request_id_from_scope(scope: Scope) -> str:
    for name, value in scope.get("headers") or []:
        if name.lower() != b"x-request-id":
            continue
        try:
            candidate = value.decode("ascii")
        except UnicodeDecodeError:
            break
        if _REQUEST_ID_PATTERN.fullmatch(candidate):
            return candidate
        break
    return str(uuid.uuid4())


class RequestCorrelationMiddleware:
    """Correlate application logs and responses with one safe request ID."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = _request_id_from_scope(scope)
        scope.setdefault("state", {})["request_id"] = correlation_id
        token = bind_request_id(correlation_id)
        started = time.perf_counter()
        status_code = 500

        async def add_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                MutableHeaders(scope=message)["X-Request-ID"] = correlation_id
            await send(message)

        try:
            await self.app(scope, receive, add_request_id)
        # This is the application-wide observation boundary; re-raise after
        # attaching correlation metadata so Starlette retains error handling.
        except Exception:  # pylint: disable=broad-exception-caught
            _REQUEST_LOGGER.exception(
                "HTTP request failed",
                extra={
                    "http_method": scope.get("method", ""),
                    "http_path": scope.get("path", ""),
                    "http_status": status_code,
                    "duration_ms": round(
                        (time.perf_counter() - started) * 1000,
                        3,
                    ),
                },
            )
            raise
        else:
            _REQUEST_LOGGER.info(
                "HTTP request completed",
                extra={
                    "http_method": scope.get("method", ""),
                    "http_path": scope.get("path", ""),
                    "http_status": status_code,
                    "duration_ms": round(
                        (time.perf_counter() - started) * 1000,
                        3,
                    ),
                },
            )
        finally:
            reset_request_id(token)

class _RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    """Reject oversized declared and streamed request bodies.

    Checking only ``Content-Length`` is insufficient because HTTP/1.1 chunked and
    HTTP/2 requests may omit it. The wrapped receive callable enforces the same
    limit on bytes the application actually consumes.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.app = app
        self.max_bytes = int(max_bytes)

    async def _error(
        self, scope: Scope, receive: Receive, send: Send, status: int, detail: str
    ) -> None:
        await JSONResponse(status_code=status, content={"detail": detail})(
            scope, receive, send
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                declared_length = int(raw_length)
            except (TypeError, ValueError):
                await self._error(scope, receive, send, 400, "Invalid Content-Length")
                return
            if declared_length < 0:
                await self._error(scope, receive, send, 400, "Invalid Content-Length")
                return
            if declared_length > self.max_bytes:
                await self._error(
                    scope,
                    receive,
                    send,
                    413,
                    f"Request body too large (max {self.max_bytes} bytes)",
                )
                return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _RequestBodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _RequestBodyTooLarge:
            # Request parsing normally happens before a response begins. If an
            # endpoint streamed early, the connection must be aborted instead of
            # attempting to emit a second response.
            if response_started:
                raise
            await self._error(
                scope,
                receive,
                send,
                413,
                f"Request body too large (max {self.max_bytes} bytes)",
            )


class SecurityHeadersMiddleware:
    """Apply browser-safe defaults without changing endpoint payloads."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def add_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, add_headers)
