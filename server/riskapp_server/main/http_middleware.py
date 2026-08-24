"""Small ASGI middleware used by the API boundary."""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


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
