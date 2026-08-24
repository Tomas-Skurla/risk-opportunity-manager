#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-python3}"
MIN_MINOR=11
MAX_MINOR=14
RECREATE=0

case "${1:-}" in
  --recreate)
    RECREATE=1
    ;;
  "")
    ;;
  *)
    echo "Usage: $0 [--recreate]"
    exit 2
    ;;
esac

echo "Using Python executable: $PYTHON_BIN"
"$PYTHON_BIN" --version

if ! "$PYTHON_BIN" - "$MIN_MINOR" "$MAX_MINOR" <<'PY'
import sys

min_minor = int(sys.argv[1])
max_minor = int(sys.argv[2])

major = sys.version_info.major
minor = sys.version_info.minor

if major != 3 or not (min_minor <= minor <= max_minor):
    raise SystemExit(
        f"ERROR: Expected Python 3.{min_minor} through 3.{max_minor}, "
        f"got Python {major}.{minor}"
    )

print(f"Python version accepted: {major}.{minor}")
PY
then
  echo
  echo "Use another interpreter with:"
  echo "  PYTHON_BIN=/path/to/python3.11 bash scripts/setup_python_env.sh"
  echo "  PYTHON_BIN=/path/to/python3.12 bash scripts/setup_python_env.sh"
  echo "  PYTHON_BIN=/path/to/python3.13 bash scripts/setup_python_env.sh"
  echo "  PYTHON_BIN=/path/to/python3.14 bash scripts/setup_python_env.sh"
  exit 1
fi

if [[ "$RECREATE" -eq 1 && -d .venv ]]; then
  echo "Recreating .venv..."
  rm -rf .venv
fi

if [[ ! -d .venv ]]; then
  echo "Creating .venv..."
  "$PYTHON_BIN" -m venv .venv
else
  echo "Reusing existing .venv (pass --recreate for a clean environment)."
fi
# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip setuptools wheel

echo "Installing server locked dependencies..."
python -m pip install -r server/requirements.lock

echo "Installing client locked dependencies..."
python -m pip install -r client/requirements.lock

echo "Installing development dependencies..."
python -m pip install -r requirements-dev.txt

echo "Running pip check..."
python -m pip check

echo "Verifying imports..."
python - <<'PY'
import sys
import fastapi
import pydantic
import pydantic_core
import sqlalchemy
import PySide6
import qdarktheme
import pytest

print("Python:", sys.version)
print("FastAPI:", fastapi.__version__)
print("Pydantic:", pydantic.__version__)
print("pydantic-core:", pydantic_core.__version__)
print("SQLAlchemy:", sqlalchemy.__version__)
print("PySide6:", PySide6.__version__)
print("qdarktheme:", qdarktheme.__file__)
print("pytest:", pytest.__version__)
print("imports ok")
PY

echo
echo "Environment ready."
echo "Activate with:"
echo "  source .venv/bin/activate"