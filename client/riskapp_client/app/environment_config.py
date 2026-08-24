"""Application settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    """Runtime configuration for the desktop client."""

    base_url: str
    email: str
    password: str
    local_db_path: Path
    allow_http_anywhere: bool

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

        return cls(
            base_url=base_url,
            email=email,
            password=password,
            local_db_path=Path(local_db).expanduser(),
            allow_http_anywhere=allow_http_anywhere,
        )
