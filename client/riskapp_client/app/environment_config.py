"""Application settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _seconds_from_env(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer number of seconds") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


@dataclass(frozen=True)
class AppConfig:
    """Runtime configuration for the desktop client."""

    base_url: str
    email: str
    password: str
    local_db_path: Path
    allow_http_anywhere: bool
    auto_sync_interval_seconds: int = 60
    auto_sync_max_backoff_seconds: int = 300

    @classmethod
    def from_env(cls) -> AppConfig:
        base_url = os.environ.get("RISKAPP_URL", "http://localhost:8000").strip()
        email = os.environ.get("RISKAPP_EMAIL", "").strip()
        password = os.environ.get("RISKAPP_PASSWORD", "").strip()

        local_db = os.environ.get(
            "RISKAPP_LOCAL_DB",
            str(Path.home() / ".riskapp" / "client.sqlite3"),
        )

        allow_http_anywhere = os.environ.get("RISKAPP_ALLOW_HTTP", "").strip() == "1"
        auto_sync_interval_seconds = _seconds_from_env(
            "RISKAPP_AUTO_SYNC_INTERVAL_SECONDS",
            60,
        )
        auto_sync_max_backoff_seconds = _seconds_from_env(
            "RISKAPP_AUTO_SYNC_MAX_BACKOFF_SECONDS",
            300,
            minimum=5,
        )

        return cls(
            base_url=base_url,
            email=email,
            password=password,
            local_db_path=Path(local_db).expanduser(),
            allow_http_anywhere=allow_http_anywhere,
            auto_sync_interval_seconds=auto_sync_interval_seconds,
            auto_sync_max_backoff_seconds=auto_sync_max_backoff_seconds,
        )
