# Setup guide

Use Python 3.14 and one virtual environment, `.venv`, for both the server and client. Run commands from the repository root. Choose the instructions for your operating system: Linux/WSL uses `.venv/bin`, while native Windows uses `.venv/Scripts`. Keep separate environments for Windows and WSL; do not reuse one across them.

## 1. Install

### Linux and WSL installation

On Ubuntu 24.04 or newer, install the packages below. Other distributions need their equivalents.

```bash
sudo apt install -y git curl python3-venv \
  libdbus-1-3 libegl1 libgl1 libfontconfig1 libglib2.0-0t64 libx11-xcb1 \
  libxkbcommon-x11-0 libxcb1 libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
  libxcb-keysyms1 libxcb-randr0 libxcb-render0 libxcb-render-util0 \
  libxcb-shape0 libxcb-shm0 libxcb-sync1 libxcb-xfixes0 libxcb-xinerama0 libxcb-xkb1
bash scripts/setup_python_env.sh
bash scripts/diagnose_qt_runtime.sh
```

The `lib*` packages are the Qt runtime libraries PySide6 needs, for the desktop client and for the headless tests. On releases without `t64` packages, install `libglib2.0-0` instead of `libglib2.0-0t64`. Every locked dependency ships as a prebuilt wheel, so no compiler is needed.

`setup_python_env.sh` creates `.venv`, installs `server/requirements.txt`, `client/requirements.txt` and `requirements-dev.txt`, and checks the main imports. If your default `python3` is not 3.14, run it as `PYTHON_BIN=python3.14 bash scripts/setup_python_env.sh`. `diagnose_qt_runtime.sh` names any Qt library that is still missing.

### Windows installation

Install native Windows Python 3.14 and Git for Windows. Use **PowerShell** for setup and launch commands, use **Git Bash** for the project's Bash check scripts. The Linux setup and launch scripts assume `.venv/bin` and are not the native Windows setup path.

Paste each complete `& { ... }` block at once. It stops the remaining commands in that block when a checked operation fails. `>>` is PowerShell's continuation prompt, not text to copy. These blocks use the virtual environment's Python directly, so PowerShell activation is not required.

```powershell
& {
    $ErrorActionPreference = "Stop"
    if (-not (Test-Path -LiteralPath ".venv")) {
        py -3.14 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Could not create the Python 3.14 environment." }
    }
    $python = (Resolve-Path ".venv\Scripts\python.exe").Path
    & $python -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 14) else 'This project needs Python 3.14.')"
    if ($LASTEXITCODE -ne 0) { throw "Use a Python 3.14 virtual environment." }
    & $python -m pip install -r server/requirements.txt -r client/requirements.txt -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    & $python -m pip check
    if ($LASTEXITCODE -ne 0) { throw "Dependency consistency check failed." }
}
```

If `py` is unavailable, use the installed Python 3.14 executable for the `-m venv` command. An existing environment from another Python version or operating system must be replaced deliberately before rerunning setup.

Create the private `.env` once. This fills the same four placeholders as `dev-init.sh`, uses exclusive file creation and leaves an existing `.env` unchanged:

```powershell
& {
    $ErrorActionPreference = "Stop"
    $python = (Resolve-Path ".venv\Scripts\python.exe").Path
    @'
from pathlib import Path
import secrets

path = Path(".env")
if path.exists():
    print(".env already exists; left unchanged.")
else:
    values = {
        "SECRET_KEY": secrets.token_hex(32),
        "TOKEN_HASH_KEY": secrets.token_hex(32),
        "INITIAL_SUPERUSER_EMAIL": "admin@example.com",
        "INITIAL_SUPERUSER_PASSWORD": secrets.token_urlsafe(24) + "Aa1!",
    }
    lines = Path(".env.example").read_text(encoding="utf-8").splitlines()
    for name, value in values.items():
        placeholder = f"{name}="
        if lines.count(placeholder) != 1:
            raise SystemExit(f"Expected one blank {name} in .env.example.")
        lines[lines.index(placeholder)] = f"{name}={value}"
    with path.open("x", encoding="utf-8") as output:
        output.write("\n".join(lines) + "\n")
    print("Created .env. Read the bootstrap login credentials there locally.")
'@ | & $python -
    if ($LASTEXITCODE -ne 0) { throw ".env creation failed." }
}
```

Keep this file private and retain its keys when restoring a database. It is already excluded from Git. If it already exists, review its settings locally rather than regenerating it or printing its credentials.

## 2. Run the checks

On Linux/WSL:

```bash
bash scripts/check_project.sh
```

On native Windows, open **Git Bash** at the repository root and activate the Windows environment before checking:

```bash
source .venv/Scripts/activate && bash scripts/check_project.sh
```

It uses the active environment or activates `.venv`, then runs in order:

1. `python scripts/check_migrations.py`: migrates an empty database to the Alembic head and checks the models for drift
2. `bash scripts/test.sh`: the test suite, with 90% combined, 92% line and 80% branch coverage gates
3. `bash scripts/typecheck.sh`: mypy on both application packages
4. `bash scripts/lint.sh`: Ruff, including its Bandit-derived `S` security rules
5. `python -m compileall -q server client scripts`
6. `python -m pip check`

`--fix` applies Ruff's safe fixes first. `bash scripts/format.sh` runs Black and rewrites files, so it is not part of the check. The tests need no display. To run one area, pass its folder to pytest, for example `python -m pytest tests/server/api/sync`, the coverage gates apply only to the full run. Tool settings live in `pyproject.toml`.

## 3. Start the server and the client

### Linux and WSL startup

```bash
bash scripts/dev-init.sh          # once: creates .env with random keys and an admin password
bash scripts/run_server_dev.sh    # terminal 1: API at http://127.0.0.1:8000
bash scripts/run_client_dev.sh    # terminal 2: desktop client
```

`dev-init.sh` writes a private, Git-ignored `.env` and never overwrites an existing one. Log in with `INITIAL_SUPERUSER_EMAIL` and `INITIAL_SUPERUSER_PASSWORD` from it. On startup the server creates that account if the email does not exist yet; it never changes an existing account.

The server launcher loads `.env` (exported variables take precedence), reloads on code changes and listens on `127.0.0.1` only, `RISKAPP_HOST` and `RISKAPP_PORT` change that. Check it with `curl http://127.0.0.1:8000/health`, which returns `{"status":"ok","db":"ok"}`. The client launcher sets `RISKAPP_URL=http://127.0.0.1:8000` and `RISKAPP_ALLOW_HTTP=1`. Using the app is covered in the [client guide](../client/README_CLIENT.md).

Without the launchers, activate `.venv` with `source .venv/bin/activate`, then run the server from `server/` and the client from `client/`:

```bash
uvicorn riskapp_server.main.app:create_app --factory --env-file ../.env --reload --host 127.0.0.1 --port 8000
RISKAPP_ALLOW_HTTP=1 RISKAPP_URL=http://127.0.0.1:8000 python -m riskapp_client.app
```

### Windows startup

Use fresh PowerShell terminals so earlier rehearsal settings do not carry over. First complete Windows installation and `.env` creation above. In the **server terminal**:

```powershell
& {
    $ErrorActionPreference = "Stop"
    $repoPath = (Resolve-Path .).Path
    $python = Join-Path $repoPath ".venv\Scripts\python.exe"
    $env:ENV = "development"
    $env:AUTO_CREATE_SCHEMA = "1"
    $env:ENFORCE_HTTPS = "0"
    $env:ALLOWED_HOSTS = "127.0.0.1,localhost"
    $env:DATABASE_URL = "sqlite+pysqlite:///" + ((Join-Path $repoPath "server\riskapp.db").Replace("\", "/"))
    Push-Location (Join-Path $repoPath "server")
    try {
        & $python -m uvicorn riskapp_server.main.app:create_app --factory `
            --env-file (Join-Path $repoPath ".env") --host 127.0.0.1 --port 8000
    } finally {
        Pop-Location
    }
}
```

Wait for `Application startup complete`. In another terminal, `Invoke-RestMethod "http://127.0.0.1:8000/health"` should report `status: ok` and `db: ok`. In the **client terminal**, at the repository root:

```powershell
& {
    $ErrorActionPreference = "Stop"
    $repoPath = (Resolve-Path .).Path
    $python = Join-Path $repoPath ".venv\Scripts\python.exe"
    $env:RISKAPP_URL = "http://127.0.0.1:8000"
    $env:RISKAPP_ALLOW_HTTP = "1"
    $env:RISKAPP_LOCAL_DB = Join-Path $env:USERPROFILE ".riskapp\client.sqlite3"
    $env:RISKAPP_AUTO_SYNC_INTERVAL_SECONDS = "60"
    Push-Location (Join-Path $repoPath "client")
    try {
        & $python -m riskapp_client.app
    } finally {
        Pop-Location
    }
}
```

Log in using the bootstrap email and password from `.env`. These are normal development paths; startup retains existing data. For disposable databases on port `8001`, use the [Windows rehearsal](DEMO_REHEARSAL.md) instead. Close the client normally and stop the API with **Ctrl+C** when finished.

### Schema migrations

For staging or production, run the migrations once before starting the API, with `DATABASE_URL` set explicitly, and keep `AUTO_CREATE_SCHEMA=0`:

```bash
export DATABASE_URL='sqlite+pysqlite:////absolute/path/to/riskapp.db'
bash scripts/migrate_server.sh
```

A database created by automatic schema creation must be backed up and verified before it is stamped with the baseline revision; do not stamp it blindly.

## 4. Run the API in Docker

Only the API runs in a container; the desktop client stays native.

```bash
bash scripts/dev-init.sh              # Linux/WSL; Windows uses the .env block above
docker compose up --build              # API at http://127.0.0.1:8000
curl http://127.0.0.1:8000/health      # from another terminal
docker compose down                    # stops it and keeps the data; --volumes deletes it
```

On Windows, create `.env` with the PowerShell block above, then run the Docker commands from PowerShell; use `Invoke-RestMethod` for the health check.

Compose reads `.env`, with variables exported in your shell taking precedence, and refuses to start without both keys. `docker compose config --quiet` validates the setup without printing secrets. For another host port, run `RISKAPP_HOST_PORT=8080 docker compose up --build` and start the client with `RISKAPP_URL=http://127.0.0.1:8080 bash scripts/run_client_dev.sh`. `docker build --target test -t riskapp:test .` runs the full project check in a container. This is a development setup, not a production deployment recipe.

## 5. Reset local data

**This deletes the server database and the client cache, including unsynced client changes.** Normal startup never deletes data. These are deliberate development resets, not rehearsal cleanup, the [rehearsal cleanup](DEMO_REHEARSAL.md#cleanup) removes only its disposable folder.

```bash
bash scripts/reset_dev_state.sh        # asks first, --yes skips the question
```

It removes `server/riskapp.db` and `~/.riskapp/client.sqlite3`. To reset one side only, start its launcher with `RESET_SERVER_DB=1` or `RESET_CLIENT_DB=1`.

## 6. Update dependencies

Version ranges live in `server/requirements.in` and `client/requirements.in`, edit those. The matching `requirements.txt` files are generated by [pip-tools](https://github.com/jazzband/pip-tools), pin every package including indirect ones, and are never edited by hand. After changing a range:

```bash
bash scripts/relock_python_deps.sh       # --upgrade for newest allowed, --upgrade-package NAME for one
bash scripts/setup_python_env.sh --recreate
```

Existing pins that still fit their range are kept. To resolve a merge conflict in a pinned file, resolve `requirements.in`, take either side of the pinned file, and rerun the script. Dependabot uses the same pip-compile options.

## 7. Configuration

The server reads its settings from the environment; the launcher and Compose also load `.env`. Invalid values stop startup. The ones you are most likely to need:

| Variable | Default | Notes |
| --- | --- | --- |
| `SECRET_KEY` | none | Signs access tokens. Required, at least 32 characters |
| `TOKEN_HASH_KEY` | none | Hashes stored refresh and reset tokens. Required, at least 32 characters, generated separately from `SECRET_KEY` |
| `ENV` | `development` | `development`, `test` or `production` |
| `DATABASE_URL` | `sqlite+pysqlite:///./riskapp.db` | Relative paths resolve against the server's working directory |
| `AUTO_CREATE_SCHEMA` | `1`; `0` in production | Production uses migrations |
| `ALLOWED_HOSTS` | `*`; required in production | Comma-separated Host values |
| `CORS_ORIGINS` | none | Comma-separated origins; `*` is rejected |
| `ENFORCE_HTTPS` | `0`; `1` in production | Rejects plain HTTP requests |
| `TRUST_X_FORWARDED_PROTO` | `0` | Enable only behind a trusted proxy |
| `INITIAL_SUPERUSER_EMAIL`, `INITIAL_SUPERUSER_PASSWORD` | none | Create-only bootstrap account; set both or neither |
| `ACCESS_TOKEN_MINUTES`, `REFRESH_TOKEN_DAYS` | `15`, `30` | Token lifetimes |
| `LOGIN_RATE_LIMIT_PER_MINUTE`, `LOGIN_IP_RATE_LIMIT_PER_MINUTE` | `10`, `50` | Login attempts per IP and email, and per IP |
| `MAX_REQUEST_BODY_BYTES` | `2097152` | Larger requests get HTTP 413 |
| `RETENTION_DAYS`, `SYNC_RECEIPT_RETENTION_DAYS` | `180`, `365` | Default age for audit pruning; receipts younger than the second are never pruned |
| `RISKAPP_LOG_LEVEL`, `RISKAPP_LOG_FORMAT` | `INFO`, `plain` | `json` for log collectors |
| `RISKAPP_HOST`, `RISKAPP_PORT` | `127.0.0.1`, `8000` | Listen address and port |

The other settings, such as the password policy, refresh-token reuse grace, database pool, gzip and sync limits, are defined with their defaults and allowed ranges in `server/riskapp_server/core/config.py`. Compose also reads `RISKAPP_HOST_ADDR` and `RISKAPP_HOST_PORT` (default `127.0.0.1` and `8000`) for the address it publishes the API on.

The client reads:

| Variable | Default | Notes |
| --- | --- | --- |
| `RISKAPP_URL` | `http://localhost:8000` | Server URL; the launcher uses `http://127.0.0.1:8000` |
| `RISKAPP_ALLOW_HTTP` | unset | `1` allows plain HTTP to hosts other than localhost |
| `RISKAPP_LOCAL_DB` | `~/.riskapp/client.sqlite3` | Local cache and outbox |
| `RISKAPP_EMAIL`, `RISKAPP_PASSWORD` | unset | When both are set, the client logs in without showing the login dialog |
| `RISKAPP_AUTO_SYNC_INTERVAL_SECONDS` | `60` | `0` turns automatic sync off |
| `RISKAPP_AUTO_SYNC_MAX_BACKOFF_SECONDS` | `300` | Longest wait between retries after failures |
| `RISKAPP_LOG_LEVEL` | `INFO` | Python log level |
