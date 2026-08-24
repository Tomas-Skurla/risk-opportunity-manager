#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  echo "ERROR: Missing .venv. Run scripts/setup_python_env.sh first."
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

export ALLOW_INSECURE_DEFAULT_SECRET="${ALLOW_INSECURE_DEFAULT_SECRET:-1}"
export INITIAL_SUPERUSER_EMAIL="${INITIAL_SUPERUSER_EMAIL:-admin@example.com}"
export INITIAL_SUPERUSER_PASSWORD="${INITIAL_SUPERUSER_PASSWORD:-SuperHeslo123!}"

if [[ "${RESET_SERVER_DB:-0}" == "1" ]]; then
  echo "Removing server/riskapp.db..."
  rm -f server/riskapp.db
fi

cd server

exec uvicorn riskapp_server.main.app:app \
  --reload \
  --host "${RISKAPP_HOST:-127.0.0.1}" \
  --port "${RISKAPP_PORT:-8000}"