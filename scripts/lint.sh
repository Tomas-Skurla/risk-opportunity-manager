#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python -m ruff check --config pyproject.toml server client tests scripts "$@"
