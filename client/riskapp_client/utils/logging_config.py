from __future__ import annotations

import logging
import os


def configure_logging() -> None:
    """Configure root logging from RISKAPP_LOG_LEVEL."""

    level_name = os.environ.get("RISKAPP_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
