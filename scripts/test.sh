#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

coverage_parent="${TMPDIR:-${RUNNER_TEMP:-/tmp}}"
if [[ ! -d "$coverage_parent" || ! -w "$coverage_parent" ]]; then
  coverage_parent="$(git rev-parse --absolute-git-dir 2>/dev/null || pwd -P)"
fi
coverage_dir="$(mktemp -d "${coverage_parent%/}/riskapp-coverage.XXXXXX")"
coverage_report="${coverage_dir}/report.json"

cleanup_coverage_report() {
  if [[ -e "$coverage_report" ]]; then
    unlink "$coverage_report"
  fi
  if [[ -d "$coverage_dir" ]]; then
    rmdir "$coverage_dir"
  fi
}
trap cleanup_coverage_report EXIT

coverage_report_python="$coverage_report"
if command -v cygpath >/dev/null 2>&1; then
  # Git Bash converts bare paths differently from pytest's embedded json: path.
  coverage_report_python="$(cygpath -m "$coverage_report")"
fi

python -m pytest -c pyproject.toml -q \
  --cov=server/riskapp_server \
  --cov=client/riskapp_client \
  --cov-branch \
  --cov-fail-under=90 \
  --cov-report=term-missing \
  --cov-report="json:${coverage_report_python}" \
  "$@"

python scripts/check_coverage_thresholds.py \
  "$coverage_report_python" \
  --min-lines=92 \
  --min-branches=80
