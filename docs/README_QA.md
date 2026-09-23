# Development quality workflow

Configuration is centralized in the repository-level `pyproject.toml`, and the canonical suite lives in `tests/`.

## One command

```bash
bash scripts/check_project.sh
```

This runs:

1. `python scripts/check_migrations.py` (empty database to Alembic head, then drift detection)
2. `bash scripts/test.sh` (90% combined, 92% line, and 80% branch coverage ratchets)
3. `bash scripts/typecheck.sh` (both complete application packages)
4. `bash scripts/lint.sh`
5. `python -m compileall -q server client scripts`
6. `python -m pip check`

The script uses an already-active environment, or activates `.venv` when present.
Install the complete test environment with:

```bash
python -m pip install -r requirements-test.txt
```

## Individual commands

```bash
bash scripts/test.sh
python scripts/check_migrations.py
bash scripts/typecheck.sh
bash scripts/lint.sh
bash scripts/format.sh       # intentionally rewrites files
bash scripts/check_project.sh --fix
```

The canonical suite includes headless Qt interaction tests. Install the client lock file and the OS packages from `scripts/setup_os_prereqs.sh --headless-gui` before running the complete suite.

Mypy checks all modules under `server/riskapp_server` and `client/riskapp_client`. Strict function annotations, unreachable-code checks, extra checks, and unused-ignore checks are enabled package-wide. Only generated Qt `ui_*.py` modules have a narrow override because they are regenerated from Designer forms rather than maintained by hand.

Ruff includes its Bandit-derived `S` security rules. The configured test exceptions cover assertions, obvious fixture credentials, and two narrowly scoped platform fixtures. Production suppressions remain line-specific and must document the validation or fixed input that makes the flagged operation safe.

CI additionally pins third-party actions by full commit SHA. Its container job uses Trivy for repository secret scanning and actionable image vulnerability/secret scanning, then uploads image findings as SARIF when the event has permission. `security-events: write` is scoped to that job.

## Qt Designer forms

The editable Qt Designer sources live in:

```text
client/riskapp_client/ui_v2/forms/
```

After editing a form in Qt Designer, regenerate only its matching `ui_*.py` from the repository root using the pinned PySide6 environment. For example:

```bash
pyside6-uic client/riskapp_client/ui_v2/forms/conflict_center_dialog.ui -o client/riskapp_client/ui_v2/ui/ui_conflict_center_dialog.py
```

For a different form, substitute its name in both paths. Regenerate only forms whose designs you intend to integrate.

Keep button behavior and dynamic merge rows in the `components/` files so form regeneration cannot overwrite them. The conflict forms use lowercase names in their Designer `<class>` tags; the components alias the resulting generated class names on import.
