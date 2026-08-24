from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication  # pylint: disable=no-name-in-module

from riskapp_client.app.application_bootstrap import build_main_window
from riskapp_client.app.environment_config import AppConfig
from riskapp_client.utils.logging_config import configure_logging


def main() -> int:
    """Run the Qt event loop."""
    configure_logging()
    app = QApplication(sys.argv)
    window = build_main_window(AppConfig.from_env())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
