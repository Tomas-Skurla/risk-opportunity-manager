# Documentation

Start here if you are setting up, testing, or running RiskApp locally.

## Main guides

- [`SETUP_GUIDE.md`](SETUP_GUIDE.md) — clean local setup, supported Python versions, script-based environment setup, server/client startup, login, offline modes, roles, tabs, and environment variables.
- [`TEST_GUIDE.md`](TEST_GUIDE.md) — manual and automated verification checklist for a clean install.
- [`client/README_CLIENT.md`](client/README_CLIENT.md) — client-specific usage, configuration, offline behavior, sync notes, and Qt/PySide diagnostics.
- [`server/README_SERVER.md`](server/README_SERVER.md) — backend startup, auth/bootstrap, configuration, and operational notes.
- [`README_QA.md`](README_QA.md) — pytest, Ruff, Black, and quality command details.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — boundaries, sync invariants, security, and trade-offs.

## Script workflow

The repository now uses project-level scripts from `scripts/` for repeatable setup and dev execution:

```text
scripts/
  setup_os_prereqs.sh       # best-effort OS package prerequisites for apt/dnf/yum/pacman/zypper/apk/brew
  setup_python_env.sh       # creates .venv and installs runtime locks + dev tools
  check_project.sh          # runs tests, lint, and pip check
  diagnose_qt_runtime.sh    # diagnoses missing PySide6/Qt native libraries
  relock_python_deps.sh     # regenerates server/client lock files separately
  reset_dev_state.sh        # removes dev SQLite DBs
  run_server_dev.sh         # starts FastAPI dev server
  run_client_dev.sh         # starts PySide6 client
  bootstrap_dev.sh          # orchestration wrapper around setup/check scripts
```

Most users should start with:

```bash
bash scripts/setup_os_prereqs.sh --desktop
bash scripts/setup_python_env.sh
bash scripts/diagnose_qt_runtime.sh
bash scripts/check_project.sh
```

Then run the app:

```bash
RESET_SERVER_DB=1 bash scripts/run_server_dev.sh
RESET_CLIENT_DB=1 bash scripts/run_client_dev.sh
```

## Dependency policy

- `server/requirements.lock` and `client/requirements.lock` are the reproducible install inputs for clean-machine validation.
- `server/requirements.txt` and `client/requirements.txt` are the source/range inputs used when regenerating the lock files.
- `requirements-test.txt` is the canonical aggregate for the complete test environment.
- `pyproject.toml` configures pytest, Ruff, and Black. It is not a dependency lock.
- `requirements-dev.txt` installs development tooling.
