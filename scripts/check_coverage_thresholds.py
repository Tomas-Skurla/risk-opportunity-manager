#!/usr/bin/env python3
"""Enforce independent line and branch coverage thresholds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _percentage(covered: int, total: int) -> float:
    return 100.0 if total == 0 else covered * 100.0 / total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("coverage_json", type=Path)
    parser.add_argument("--min-lines", type=float, required=True)
    parser.add_argument("--min-branches", type=float, required=True)
    args = parser.parse_args()

    with args.coverage_json.open(encoding="utf-8") as report_file:
        totals = json.load(report_file)["totals"]

    line_coverage = _percentage(
        int(totals["covered_lines"]), int(totals["num_statements"])
    )
    branch_coverage = _percentage(
        int(totals["covered_branches"]), int(totals["num_branches"])
    )
    print(
        "Coverage thresholds: "
        f"lines {line_coverage:.2f}% (minimum {args.min_lines:.2f}%), "
        f"branches {branch_coverage:.2f}% (minimum {args.min_branches:.2f}%)"
    )

    failures: list[str] = []
    if line_coverage < args.min_lines:
        failures.append("line coverage")
    if branch_coverage < args.min_branches:
        failures.append("branch coverage")
    if failures:
        print("Coverage gate failed: " + " and ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
