#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-python3}"
MIN_MINOR=11
MAX_MINOR=14

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

print(f"Python version accepted for relocking: {major}.{minor}")
PY
then
  echo
  echo "Use another interpreter with:"
  echo "  PYTHON_BIN=/path/to/python3.11 bash scripts/relock_python_deps.sh"
  echo "  PYTHON_BIN=/path/to/python3.12 bash scripts/relock_python_deps.sh"
  echo "  PYTHON_BIN=/path/to/python3.13 bash scripts/relock_python_deps.sh"
  echo "  PYTHON_BIN=/path/to/python3.14 bash scripts/relock_python_deps.sh"
  exit 1
fi

timestamp="$(date +%Y%m%d%H%M%S)"
server_lock_env="$(mktemp -d -t riskapp-server-lock.XXXXXX)"
client_lock_env="$(mktemp -d -t riskapp-client-lock.XXXXXX)"

cleanup() {
  rm -rf -- "$server_lock_env" "$client_lock_env"
}
trap cleanup EXIT

echo "Backing up existing lock files..."
if [[ -f server/requirements.lock ]]; then
  cp server/requirements.lock "server/requirements.lock.before-relock.$timestamp"
fi

if [[ -f client/requirements.lock ]]; then
  cp client/requirements.lock "client/requirements.lock.before-relock.$timestamp"
fi

echo "Regenerating server lock..."
"$PYTHON_BIN" -m venv "$server_lock_env"
# shellcheck disable=SC1091
source "$server_lock_env/bin/activate"
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r server/requirements.txt
python -m pip check
python -m pip freeze > server/requirements.lock
deactivate

echo "Regenerating client lock..."
"$PYTHON_BIN" -m venv "$client_lock_env"
# shellcheck disable=SC1091
source "$client_lock_env/bin/activate"
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r client/requirements.txt
python -m pip check
python -m pip freeze > client/requirements.lock
deactivate

echo
echo "Server dependency highlights:"
grep -nE "alembic|fastapi|starlette|pydantic|pydantic-core|sqlalchemy|uvicorn" server/requirements.lock || true

echo
echo "Client dependency highlights:"
grep -nE "PySide6|PySide6_Addons|PySide6_Essentials|shiboken6|DarkTheme|darktheme|darkdetect" client/requirements.lock || true

echo
echo "Relock complete."
echo
echo "Next:"
echo "  bash scripts/setup_python_env.sh"
echo "  bash scripts/check_project.sh"