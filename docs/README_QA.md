# Development quality workflow

Configuration is centralized in the repository-level `pyproject.toml`, and the canonical suite lives in `tests/`.

## One command

```bash
bash scripts/check_project.sh
```

This runs:

1. `python scripts/check_migrations.py` (empty database to Alembic head, then drift detection)
2. `bash scripts/test.sh` (90% combined, 92% line, and 80% branch coverage ratchets)
3. `bash scripts/typecheck.sh` (incremental mypy module allowlist)
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

Mypy is intentionally incremental: `[tool.mypy].files` in `pyproject.toml` is the reviewed module allowlist. Add modules as their existing findings are fixed; do not replace the allowlist with the whole repository and suppress the result.

Ruff includes its Bandit-derived `S` security rules. The configured test exceptions cover assertions, obvious fixture credentials, and two narrowly scoped platform fixtures. Production suppressions remain line-specific and must document the validation or fixed input that makes the flagged operation safe.

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
