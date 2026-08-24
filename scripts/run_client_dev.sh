#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  echo "ERROR: Missing .venv. Run scripts/setup_python_env.sh first."
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

export RISKAPP_ALLOW_HTTP="${RISKAPP_ALLOW_HTTP:-1}"
export RISKAPP_URL="${RISKAPP_URL:-http://127.0.0.1:8000}"
export RISKAPP_API_BASE_URL="${RISKAPP_API_BASE_URL:-$RISKAPP_URL}"

if [[ "${RESET_CLIENT_DB:-0}" == "1" ]]; then
  echo "Removing ~/.riskapp/client.sqlite3..."
  rm -f "$HOME/.riskapp/client.sqlite3"
fi

cd client

exec python -m riskapp_client.app