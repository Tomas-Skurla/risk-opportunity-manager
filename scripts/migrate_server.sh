#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -z "${VIRTUAL_ENV:-}" && -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: DATABASE_URL must be set explicitly before running migrations."
  exit 1
fi

export AUTO_CREATE_SCHEMA=0

python -m alembic upgrade head
python -m alembic current --check-heads

echo "Server database is at the latest migration."