#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Check both complete application packages. Generated Qt modules remain
# explicitly exempted through the narrow override in pyproject.toml.
python -m mypy --config-file pyproject.toml
