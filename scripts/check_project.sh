#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

SOURCE_DIRS=(server client tests scripts)

if [[ -z "${VIRTUAL_ENV:-}" && -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if ! python -m pytest --version >/dev/null 2>&1 \
  || ! python -m ruff --version >/dev/null 2>&1 \
  || ! python -m alembic --version >/dev/null 2>&1; then
  echo "ERROR: Missing development dependencies."
  echo "Install them with: python -m pip install -r requirements-test.txt"
  exit 1
fi

case "${1:-}" in
  --fix)
    echo "Running Ruff autofix..."
    python -m ruff check --config pyproject.toml "${SOURCE_DIRS[@]}" --fix
    ;;
  "")
    ;;
  *)
    echo "Usage: $0 [--fix]"
    exit 2
    ;;
esac

echo "Checking server migrations..."
python scripts/check_migrations.py

echo "Running tests..."
bash scripts/test.sh

echo "Running lint..."
bash scripts/lint.sh

echo "Compiling Python sources..."
python -m compileall -q server client scripts

echo "Running pip check..."
python -m pip check

echo "All checks passed."