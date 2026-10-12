#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Regenerate server/requirements.txt and client/requirements.txt from the
# version ranges in the matching requirements.in files. Arguments are passed
# to pip-compile, for example:
#
#   bash scripts/relock_python_deps.sh                         # keep current pins
#   bash scripts/relock_python_deps.sh --upgrade               # newest allowed versions
#   bash scripts/relock_python_deps.sh --upgrade-package NAME  # one package

PYTHON_BIN="${PYTHON_BIN:-python3}"
REQUIRED_MINOR=14
# Not tracked by Dependabot -> CHORE: bump by hand.
PIP_TOOLS_VERSION="7.6.2"

echo "Using Python executable: $PYTHON_BIN"
"$PYTHON_BIN" --version

if ! "$PYTHON_BIN" - "$REQUIRED_MINOR" <<'PY'
import sys

required_minor = int(sys.argv[1])

major = sys.version_info.major
minor = sys.version_info.minor

if major != 3 or minor != required_minor:
    raise SystemExit(
        f"ERROR: Expected Python 3.{required_minor}, "
        f"got Python {major}.{minor}"
    )

print(f"Python version accepted for relocking: {major}.{minor}")
PY
then
  echo
  echo "Use the canonical interpreter with:"
  echo "  PYTHON_BIN=/path/to/python3.14 bash scripts/relock_python_deps.sh"
  exit 1
fi

work_dir="$(mktemp -d -t riskapp-relock.XXXXXX)"

cleanup() {
  rm -rf -- "$work_dir"
}
trap cleanup EXIT

echo "Installing pip-tools $PIP_TOOLS_VERSION..."
"$PYTHON_BIN" -m venv "$work_dir/tools"
"$work_dir/tools/bin/python" -m pip install --quiet "pip-tools==$PIP_TOOLS_VERSION"

for side in server client; do
  echo "Compiling $side/requirements.txt..."
  # Dependabot reruns pip-compile with the options in the generated header,
  # so keep this command unchanged.
  "$work_dir/tools/bin/pip-compile" --quiet --strip-extras \
    --output-file="$side/requirements.txt" "$side/requirements.in" "$@"

  echo "Checking $side/requirements.txt..."
  "$PYTHON_BIN" -m venv "$work_dir/check-$side"
  "$work_dir/check-$side/bin/python" -m pip install --quiet -r "$side/requirements.txt"
  "$work_dir/check-$side/bin/python" -m pip check
done

echo
echo "Server dependency highlights:"
grep -nE "^(alembic|fastapi|starlette|pydantic|pydantic-core|sqlalchemy|uvicorn)==" server/requirements.txt || true

echo
echo "Client dependency highlights:"
grep -nE "^(pyside6|pyside6-addons|pyside6-essentials|shiboken6|pyqtdarktheme-fork|darkdetect)==" client/requirements.txt || true

echo
echo "Relock complete."
echo
echo "Next:"
echo "  bash scripts/setup_python_env.sh --recreate"
echo "  bash scripts/check_project.sh"
