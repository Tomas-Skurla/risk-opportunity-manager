#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Runs the same CodeQL analysis as .github/workflows/codeql.yml on this
# machine and prints the findings.
#
# CI sends its results only to the Security tab, which needs write access to
# view. Printing them in CI would publish them, because logs, run summaries
# and artifacts of a public repository are readable by anyone. This script
# keeps everything local, and writes it outside the repository so that nothing
# can be committed by accident.
#
# Usage: bash scripts/codeql_local.sh
#
#   CODEQL=/path/to/codeql   use an existing CodeQL CLI instead of the bundle
#   CODEQL_LOCAL_DIR=/path   where the bundle, database and results are kept
#                            (default: ~/.cache/codeql-local)
#
# The first run downloads the CodeQL bundle (about 1.4 GB once unpacked).
# Later runs reuse it.

# Keep both in step with CI: the bundle version is shown in the log of the
# "Analyze Python" step, and the suite matches `queries:` in codeql.yml.
CODEQL_VERSION="2.27.1"
BASE_SUITE="codeql-suites/python-security-and-quality.qls"

# Queries left out of the local report. Only quality queries belong here;
# never exclude a security query.
#
# py/ineffectual-statement: flags every `...` body of a Protocol method and
#   `await result` in a plain coroutine, so on this code base it reports only
#   false positives. Ruff's B018 (useless-expression) and B015
#   (useless-comparison), already enabled in pyproject.toml, cover the real
#   cases and understand `...`.

# py/import-and-import-from: a style rule. Its only hits are tests that import
#   a module as a handle for monkeypatching or for attributes rebuilt by
#   isolated_app_factory, and import names from it for readability.
EXCLUDED_QUERIES=(
  py/ineffectual-statement
  py/import-and-import-from
)

# Generated files whose findings are dropped from the report and the SARIF,
# matching the Ruff exclude in pyproject.toml (pyside6-uic output). They are
# still analysed, so code that uses them is understood correctly; only results
# located inside them are removed. `*` matches within a single path segment.
GENERATED_PATHS=(
  "client/riskapp_client/ui_v2/ui/ui_*.py"
)

# Known false positives of one rule in specific files, as "<rule id> <path>".
# Unlike EXCLUDED_QUERIES, the rule keeps reporting everywhere else. Paths use
# the same pattern syntax as GENERATED_PATHS. Every entry needs a reason.
#
# py/unused-global-variable decides what a module exports with CodeQL's older
# points-to library, which treats none of these names as exported:
#   - config.py: every flagged setting is imported and used by other modules.
#     (The data-flow library behind the security queries resolves those
#     imports correctly.)
#   - Alembic revisions: Alembic reads revision, down_revision, branch_labels
#     and depends_on from each migration module by name.

# py/conflicting-attributes does not treat `if TYPE_CHECKING:` blocks as absent
# at runtime, and MainWindow's mixins keep their sibling declarations there.
# tests/client/gui/test_main_window_composition.py checks the real runtime
# rule instead: no two mixins define the same attribute.
IGNORED_FINDINGS=(
  "py/unused-global-variable server/riskapp_server/core/config.py"
  "py/unused-global-variable server/alembic/versions/*.py"
  "py/conflicting-attributes client/riskapp_client/ui_v2/main_application_window.py"
)

repo_dir="$(pwd -P)"
base_dir="${CODEQL_LOCAL_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/codeql-local}"
mkdir -p "$base_dir"
base_dir="$(cd "$base_dir" && pwd -P)"

case "$base_dir/" in
  "$repo_dir"/*)
    echo "ERROR: CODEQL_LOCAL_DIR must be outside the repository: $base_dir"
    exit 2
    ;;
esac

work_dir="$base_dir/$(basename "$repo_dir")"
src_dir="$work_dir/src"
db_dir="$work_dir/db"
sarif="$work_dir/results.sarif"
python_bin="${PYTHON:-python3}"

if ! command -v "$python_bin" >/dev/null 2>&1; then
  echo "ERROR: $python_bin not found. Set PYTHON to a Python 3 interpreter."
  exit 1
fi

# ---- CodeQL CLI ------------------------------------------------------------
if [[ -n "${CODEQL:-}" ]]; then
  codeql="$CODEQL"
else
  bundle_dir="$base_dir/codeql-$CODEQL_VERSION"
  codeql="$bundle_dir/codeql/codeql"
  if [[ ! -x "$codeql" ]]; then
    case "$(uname -s)" in
      Linux) platform=linux64 ;;
      Darwin) platform=osx64 ;;
      *)
        echo "ERROR: No CodeQL bundle download for $(uname -s)."
        echo "Install the CodeQL CLI and run: CODEQL=/path/to/codeql $0"
        exit 1
        ;;
    esac
    url="https://github.com/github/codeql-action/releases/download/codeql-bundle-v$CODEQL_VERSION/codeql-bundle-$platform.tar.gz"
    partial="$bundle_dir.partial"
    rm -rf "$partial"
    mkdir -p "$partial"
    echo "Downloading CodeQL $CODEQL_VERSION (first run only)..."
    curl --fail --location --progress-bar "$url" | tar -xzf - -C "$partial"
    rm -rf "$bundle_dir"
    mv "$partial" "$bundle_dir"
  fi
fi

# ---- Source snapshot -------------------------------------------------------
# Analyse what git sees: tracked files and new files that are not ignored,
# including uncommitted edits. Virtual environments, caches and other ignored
# files stay out, as they do in CI's checkout.
echo "Copying source files..."
rm -rf "$src_dir"
mkdir -p "$src_dir"
git ls-files -z --cached --others --exclude-standard \
  | while IFS= read -r -d '' path; do
      if [[ -e "$path" ]]; then
        printf '%s\0' "$path"
      fi
    done \
  | tar --null -T - -cf - \
  | tar -xf - -C "$src_dir"

# ---- Analysis --------------------------------------------------------------
# CodeQL's own output is long, so it goes to a log that is shown on failure.
log="$work_dir/codeql.log"
: >"$log"

run_codeql() {
  if ! "$codeql" "$@" >>"$log" 2>&1; then
    echo "ERROR: codeql $1 $2 failed. Last lines of $log:"
    tail -n 30 "$log"
    exit 1
  fi
}

echo "Creating CodeQL database..."
run_codeql database create "$db_dir" \
  --language=python \
  --build-mode=none \
  --source-root="$src_dir" \
  --overwrite \
  --threads=0

suite="$work_dir/local-suite.qls"
{
  echo "- import: $BASE_SUITE"
  echo "  from: codeql/python-queries"
  # The ${a[@]+...} form keeps an empty list working under `set -u` in the
  # older bash that macOS ships.
  for query_id in ${EXCLUDED_QUERIES[@]+"${EXCLUDED_QUERIES[@]}"}; do
    echo "- exclude:"
    echo "    id: $query_id"
  done
} >"$suite"

excluded="${EXCLUDED_QUERIES[*]+${EXCLUDED_QUERIES[*]}}"
echo "Running python-security-and-quality (excluding: ${excluded:-nothing})..."
run_codeql database analyze "$db_dir" "$suite" \
  --download \
  --format=sarif-latest \
  --output="$sarif" \
  --threads=0

rm -rf "$src_dir"
sed -n 's/^\(CodeQL scanned [^.]*\)\..*/\1./p' "$log"

# ---- Report ----------------------------------------------------------------
branch="$(git rev-parse --abbrev-ref HEAD)"
dirty=""
if [[ -n "$(git status --porcelain)" ]]; then
  dirty=" (with uncommitted changes)"
fi

CODEQL_LOCAL_GENERATED="$(printf '%s\n' ${GENERATED_PATHS[@]+"${GENERATED_PATHS[@]}"})" \
CODEQL_LOCAL_IGNORED="$(printf '%s\n' ${IGNORED_FINDINGS[@]+"${IGNORED_FINDINGS[@]}"})" \
  "$python_bin" -I - "$sarif" "$branch$dirty" <<'PY'
import json
import os
import re
import sys
from collections import Counter
from pathlib import PurePosixPath


def entries(variable):
    return [line.strip() for line in os.environ[variable].splitlines() if line.strip()]


sarif_path, label = sys.argv[1:]
generated_patterns = entries("CODEQL_LOCAL_GENERATED")
ignored_findings = [tuple(entry.split(None, 1)) for entry in entries("CODEQL_LOCAL_IGNORED")]
with open(sarif_path, encoding="utf-8") as handle:
    sarif = json.load(handle)


def position(result):
    location = result["locations"][0]["physicalLocation"]
    return location["artifactLocation"]["uri"], location["region"]["startLine"]


def where(result):
    path, line = position(result)
    return f"{path}:{line}"


def message(result):
    # CodeQL writes links to related locations as "[text](1)"; keep the text.
    text = re.sub(r"\[([^\]]+)\]\(\d+\)", r"\1", result["message"]["text"])
    return " ".join(text.split())


def hidden_reason(result):
    # Paths in the SARIF are relative to the repository root. match() works on
    # every Python 3 version (full_match() needs 3.13).
    path = PurePosixPath(position(result)[0])
    for pattern in generated_patterns:
        if path.match(pattern):
            return f"in generated files {pattern}"
    for rule, pattern in ignored_findings:
        if result["ruleId"] == rule and path.match(pattern):
            return f"{rule} in {pattern}"
    return None


# Drop generated-file findings and known false positives, and save the SARIF
# without them so that viewers show the same list as this report.
hidden = Counter()
for run in sarif["runs"]:
    kept = []
    for result in run.get("results", []):
        reason = hidden_reason(result)
        if reason:
            hidden[reason] += 1
        else:
            kept.append(result)
    run["results"] = kept
if hidden:
    with open(sarif_path, "w", encoding="utf-8") as handle:
        json.dump(sarif, handle, indent=2)

results = [result for run in sarif["runs"] for result in run["results"]]


print()
print(f"CodeQL findings on {label}: {len(results)}")
if hidden:
    print(f"Not shown ({sum(hidden.values())}, see GENERATED_PATHS and IGNORED_FINDINGS):")
    for reason, count in hidden.most_common():
        print(f"  {count:3}  {reason}")
if not results:
    print("No findings.")
    sys.exit(0)

print()
print("By rule:")
counts = Counter(result["ruleId"] for result in results)
width = max(len(rule) for rule in counts)
for rule, count in counts.most_common():
    print(f"  {rule:<{width}}  {count}")

print()
print("Findings:")
for result in sorted(results, key=lambda r: (r["ruleId"], *position(r))):
    print(f"  {result['ruleId']}  {where(result)}")
    print(f"      {message(result)}")
PY

echo
echo "Full results: $sarif"
echo "(Open it with a SARIF viewer, such as the SARIF Viewer extension for VS Code.)"
