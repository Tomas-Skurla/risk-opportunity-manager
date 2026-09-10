"""Application logging with request-correlation context."""

from __future__ import annotations

import json
import logging
import time
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

from riskapp_server.core.config import RISKAPP_LOG_FORMAT, RISKAPP_LOG_LEVEL

_REQUEST_ID: ContextVar[str] = ContextVar("riskapp_request_id", default="-")
_HANDLER_MARKER = "_riskapp_server_handler"


def request_id() -> str:
    """Return the request ID active in the current execution context."""
    return _REQUEST_ID.get()


def bind_request_id(value: str) -> Token[str]:
    """Bind a request ID and return the token needed to restore the context."""
    return _REQUEST_ID.set(value)


def reset_request_id(token: Token[str]) -> None:
    """Restore the request context represented by ``token``."""
    _REQUEST_ID.reset(token)


class RequestContextFilter(logging.Filter):
    """Attach the active request ID to every RiskApp log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.__dict__.setdefault("request_id", request_id())
        return True


class JsonFormatter(logging.Formatter):
    """Render a stable, deliberately bounded JSON log schema."""

    _EXTRA_FIELDS = (
        "http_method",
        "http_path",
        "http_status",
        "duration_ms",
    )

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).isoformat(
            timespec="milliseconds"
        )
        payload: dict[str, Any] = {
            "timestamp": timestamp.replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id()),
        }
        for field in self._EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class UtcPlainFormatter(logging.Formatter):
    """Plain formatter that uses UTC to match the JSON timestamps."""

    def converter(self, timestamp: float | None = None) -> time.struct_time:
        """Convert a Unix timestamp to UTC for ``Formatter.formatTime``."""
        return time.gmtime(timestamp)

    def format(self, record: logging.LogRecord) -> str:
        """Append request fields when formatting an HTTP request record."""
        rendered = super().format(record)
        fields = (
            ("method", "http_method"),
            ("path", "http_path"),
            ("status", "http_status"),
            ("duration_ms", "duration_ms"),
        )
        details: list[str] = []
        for label, attribute in fields:
            value = getattr(record, attribute, None)
            if value is None:
                continue
            if isinstance(value, str):
                value = json.dumps(value, ensure_ascii=True)
            details.append(f"{label}={value}")
        return f"{rendered} {' '.join(details)}" if details else rendered


def configure_server_logging(
    *, level: str = RISKAPP_LOG_LEVEL, output_format: str = RISKAPP_LOG_FORMAT
) -> None:
    """Configure RiskApp-owned loggers without replacing host/Uvicorn handlers."""
    app_logger = logging.getLogger("riskapp_server")
    app_logger.setLevel(getattr(logging, level.upper()))
    app_logger.propagate = False

    for handler in list(app_logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            app_logger.removeHandler(handler)
            handler.close()

    handler = logging.StreamHandler()
    setattr(handler, _HANDLER_MARKER, True)
    handler.addFilter(RequestContextFilter())
    if output_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            UtcPlainFormatter(
                "%(asctime)sZ %(levelname)s %(name)s "
                "request_id=%(request_id)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
    app_logger.addHandler(handler)
