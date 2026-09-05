# Development quality workflow

Configuration is centralized in the repository-level `pyproject.toml`, and the canonical suite lives in `tests/`.

## One command

```bash
bash scripts/check_project.sh
```

This runs:

1. `python scripts/check_migrations.py` (empty database to Alembic head, then drift detection)
2. `bash scripts/test.sh` (90% combined, 92% line, and 80% branch coverage ratchets)
3. `bash scripts/lint.sh`
4. `python -m compileall -q server client scripts`
5. `python -m pip check`

The script uses an already-active environment, or activates `.venv` when present.
Install the complete test environment with:

```bash
python -m pip install -r requirements-test.txt
```

## Individual commands

```bash
bash scripts/test.sh
python scripts/check_migrations.py
bash scripts/lint.sh
bash scripts/format.sh       # intentionally rewrites files
bash scripts/check_project.sh --fix
```

The canonical suite includes headless Qt interaction tests. Install the client lock file and the OS packages from `scripts/setup_os_prereqs.sh --headless-gui` before running the complete suite.

## Qt Designer forms

The Conflict Center layout is maintained in the editable Designer source:

```text
client/riskapp_client/ui_v2/components/conflict_center_dialog.ui
```

After saving it in Qt Designer, regenerate the Python form class from the repository root:

```bash
pyside6-uic client/riskapp_client/ui_v2/components/conflict_center_dialog.ui -o client/riskapp_client/ui_v2/components/ui_conflict_center_dialog.py
```

Do not edit `ui_conflict_center_dialog.py` directly; keep behavior in `conflict_center_dialog.py` so regenerating the form cannot overwrite it.
