#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  echo "ERROR: Missing .venv. Run scripts/setup_python_env.sh first."
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "Python:"
python --version

echo
echo "Import check:"
python - <<'PY'
import sys
print("Python:", sys.version)

try:
    import PySide6
    print("PySide6:", PySide6.__version__)
except Exception as exc:
    print("PySide6 import failed:", repr(exc))
    raise

try:
    import qdarktheme
    print("qdarktheme:", qdarktheme.__file__)
    print("setup_theme exists:", hasattr(qdarktheme, "setup_theme"))
except Exception as exc:
    print("qdarktheme import failed:", repr(exc))
    raise
PY

echo
echo "PySide6 location:"
PYSIDE_DIR="$(python - <<'PY'
import pathlib
import PySide6
print(pathlib.Path(PySide6.__file__).parent)
PY
)"
echo "$PYSIDE_DIR"

echo
echo "Checking QtCore linked libraries:"
QTCORE="$(find "$PYSIDE_DIR" -name 'QtCore*.so*' | head -n 1 || true)"
if [[ -n "$QTCORE" ]]; then
  echo "$QTCORE"
  ldd "$QTCORE" | grep "not found" || echo "No missing QtCore libraries detected."
else
  echo "Could not find QtCore shared object."
fi

echo
echo "Checking xcb platform plugin linked libraries:"
XCB_PLUGIN="$(find "$PYSIDE_DIR" -path '*platforms*' -name 'libqxcb.so' | head -n 1 || true)"
if [[ -n "$XCB_PLUGIN" ]]; then
  echo "$XCB_PLUGIN"
  ldd "$XCB_PLUGIN" | grep "not found" || echo "No missing xcb plugin libraries detected."
else
  echo "Could not find libqxcb.so."
fi

echo
echo "Diagnostic complete."