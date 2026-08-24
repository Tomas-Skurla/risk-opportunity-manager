"""Run the server with ``python -m riskapp_server``."""

from __future__ import annotations

import os


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    # Lazy import so this file stays importable even if uvicorn isn't installed.
    import uvicorn  # type: ignore

    env = os.getenv("ENV", "development").strip().lower()
    host = os.getenv("RISKAPP_HOST", "127.0.0.1")
    port = int(os.getenv("RISKAPP_PORT", "8000"))
    reload_enabled = _env_flag("RISKAPP_RELOAD", env == "development")
    uvicorn.run(
        "riskapp_server.main.app:app",
        host=host,
        port=port,
        reload=reload_enabled,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
