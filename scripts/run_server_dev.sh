#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  echo "ERROR: Missing .venv. Run scripts/setup_python_env.sh first."
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

server_env_args=()
if [[ -f .env ]]; then
  # Uvicorn parses dotenv data without executing it as a shell script.
  # Already-exported settings take precedence over values from the file.
  server_env_args=(--env-file "$PWD/.env")
elif [[ -z "${SECRET_KEY:-}" || -z "${TOKEN_HASH_KEY:-}" ]]; then
  echo "ERROR: Run ./scripts/dev-init.sh or export both SECRET_KEY and TOKEN_HASH_KEY." >&2
  exit 1
fi

if [[ "${RESET_SERVER_DB:-0}" == "1" ]]; then
  echo "Removing server/riskapp.db..."
  rm -f server/riskapp.db
fi

cd server

exec uvicorn riskapp_server.main.app:app \
  "${server_env_args[@]}" \
  --reload \
  --host "${RISKAPP_HOST:-127.0.0.1}" \
  --port "${RISKAPP_PORT:-8000}"
