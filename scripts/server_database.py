"""Run the SQLite server backup/recovery tool from the repository root."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

# Import after path setup so the wrapper also works outside the repository root.
# pylint: disable-next=wrong-import-position
from riskapp_server.ops.sqlite_backup import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
