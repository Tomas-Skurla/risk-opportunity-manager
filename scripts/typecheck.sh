#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# The initial module allowlist is intentionally kept in pyproject.toml. Expand
# it in small, reviewed steps instead of hiding existing repository-wide debt.
python -m mypy --config-file pyproject.toml
