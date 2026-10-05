# RiskApp — Setup Guide

This guide describes the recommended local setup using the repository scripts.

## Prerequisites

- Python 3.14. Docker, CI, Black, Ruff, mypy, and dependency relocking all use this same minor version.
- A shell capable of running Bash scripts.
- Two terminal windows for running the server and client.
- Ubuntu 24.04 or newer. Other distributions need the equivalent packages from step 2.

The project uses a **single virtual environment at the repository root**:

```text
.venv/
```

Do not create separate `server/.venv` and `client/.venv` environments for normal local testing.

---

## 1. Open the repository root

Change into the directory that contains `server/`, `client/`, `tests/`, and `scripts/`.

```bash
cd /path/to/risk-opportunity-manager
```

If you downloaded a ZIP, extract it first and then `cd` into the extracted project root.

---

## 2. Install OS prerequisites

```bash
sudo apt install -y git curl python3-venv \
  libdbus-1-3 libegl1 libgl1 libfontconfig1 libglib2.0-0t64 libx11-xcb1 \
  libxkbcommon-x11-0 libxcb1 libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
  libxcb-keysyms1 libxcb-randr0 libxcb-render0 libxcb-render-util0 \
  libxcb-shape0 libxcb-shm0 libxcb-sync1 libxcb-xfixes0 libxcb-xinerama0 libxcb-xkb1
```

The `lib*` packages are the Qt runtime libraries PySide6 needs, for both the desktop client and the headless test suite. A desktop install already has most of them, and apt skips those. Every locked Python dependency ships as a prebuilt wheel, so no compiler or Python headers are needed. If the client still fails to start, the diagnostic script in step 4 names the missing library.

---

## 3. Create the Python environment

Install server/client dependencies from the lock files and tooling from `requirements-dev.txt`:

```bash
bash scripts/setup_python_env.sh
```

If your default `python3` is not the version you want, provide an interpreter explicitly:

```bash
PYTHON_BIN=python3.14 bash scripts/setup_python_env.sh
```

The script requires Python 3.14. It creates `.venv`, installs:

```text
server/requirements.lock
client/requirements.lock
requirements-dev.txt
```

and verifies imports for FastAPI, Pydantic, SQLAlchemy, PySide6, `qdarktheme`, and pytest.

---

## 4. Diagnose Qt/PySide runtime libraries

Run this once after setting up the Python environment:

```bash
bash scripts/diagnose_qt_runtime.sh
```

If it reports missing shared libraries such as `libglib-2.0.so.0` or missing `xcb` plugin dependencies, install the corresponding OS package and rerun the diagnostic.

On Debian/Ubuntu family systems, the most common missing GLib package is one of:

```bash
sudo apt install -y libglib2.0-0
# or on newer t64-based releases:
sudo apt install -y libglib2.0-0t64
```

---

## 5. Run automated checks

```bash
bash scripts/check_project.sh
```

It uses an already active environment, or activates `.venv` when present, and runs these steps in order:

1. `python scripts/check_migrations.py`: migrates an empty database to the Alembic head, then checks the models for drift
2. `bash scripts/test.sh`: the test suite, with 90% combined, 92% line and 80% branch coverage gates
3. `bash scripts/typecheck.sh`: mypy on both application packages
4. `bash scripts/lint.sh`: Ruff
5. `python -m compileall -q server client scripts`
6. `python -m pip check`

Each step also runs on its own. If Ruff reports safe fixable issues, `bash scripts/check_project.sh --fix` applies them before checking. `bash scripts/format.sh` runs Black and rewrites files, so it is not part of the check.

The suite includes headless Qt tests. It needs the client dependencies and the OS packages from step 2, but no display.

The tests are grouped by what they exercise:

```text
tests/
  server/unit/          server code without HTTP requests
  server/api/           requests to the API: auth/, projects/, records/, sync/, http/
  server/migrations/    the Alembic migrations
  client/unit/          client code: app/, services/, storage/, sync/
  client/gui/           the desktop UI layer
  client/integration/   the client and a real server together
  support/              shared helpers for accounts, projects, items and sync changes
```

To run one area, pass its folder to pytest, for example `python -m pytest tests/server/api/sync`. Running a single area skips the coverage gates, which only apply to a full run of `bash scripts/check_project.sh`.

Configuration for pytest, mypy, Ruff and Black lives in `pyproject.toml`. Mypy checks every module under `server/riskapp_server` and `client/riskapp_client` with strict function annotations, unreachable-code, extra and unused-ignore checks. Only the generated Qt `ui_*.py` modules have a narrow override, because they are regenerated from Designer forms rather than maintained by hand. Ruff includes its Bandit-derived `S` security rules. The test exceptions cover assertions, obvious fixture credentials and two narrowly scoped platform fixtures; suppressions in application code are line-specific and document why the flagged operation is safe.

---

## 6. Start the server

Use Terminal 1:

```bash
bash scripts/dev-init.sh
RESET_SERVER_DB=1 bash scripts/run_server_dev.sh
```

The setup script creates a private, Git-ignored `.env` with random signing and token-hash keys and an administrator password. Reruns preserve existing values. The launcher loads that file, with exported settings taking precedence. Read `INITIAL_SUPERUSER_EMAIL` and `INITIAL_SUPERUSER_PASSWORD` from `.env` to log in. Existing database accounts are never changed by bootstrap settings.

The server runs at:

```text
http://127.0.0.1:8000
```

The launcher binds to `127.0.0.1`, so the API is reachable only from this machine. `RISKAPP_HOST` and `RISKAPP_PORT` change the address and port.

Verify from another terminal:

```bash
curl -s -o /tmp/riskapp-health.json -w "HTTP %{http_code}\n" http://127.0.0.1:8000/health
cat /tmp/riskapp-health.json
```

Expected:

```text
HTTP 200
{"status":"ok","db":"ok"}
```

To run the server without the launcher, for example to change uvicorn options:

```bash
source .venv/bin/activate
cd server
uvicorn riskapp_server.main.app:create_app --factory --env-file ../.env --reload --host 127.0.0.1 --port 8000
```

Deliberately resetting the development database still requires `RESET_SERVER_DB=1`, which deletes all server data.

For staging or production, run the migration job once before starting API workers. `DATABASE_URL` is intentionally required:

```bash
source .venv/bin/activate
export DATABASE_URL='sqlite+pysqlite:////absolute/path/to/riskapp.db'
bash scripts/migrate_server.sh
```

Keep `AUTO_CREATE_SCHEMA=0` in deployed environments. Existing databases made with automatic schema creation must be backed up and verified before stamping the baseline revision; do not blindly stamp them.

---

## 7. Start the client

Use Terminal 2:

```bash
RESET_CLIENT_DB=1 bash scripts/run_client_dev.sh
```

This launches the PySide6 desktop client with:

```text
RISKAPP_ALLOW_HTTP=1
RISKAPP_URL=http://127.0.0.1:8000
```

Login with:

```text
Server URL: http://127.0.0.1:8000
Email: <your admin email here>, the INITIAL_SUPERUSER_EMAIL from .env
Password: <your admin password here>, the INITIAL_SUPERUSER_PASSWORD from .env
```

To run the client without the launcher:

```bash
source .venv/bin/activate
cd client
RISKAPP_ALLOW_HTTP=1 RISKAPP_URL=http://127.0.0.1:8000 python -m riskapp_client.app
```

For using the app, including the login dialog, accounts, offline modes, roles and tabs, see the [client guide](../client/README_CLIENT.md).

---

## 8. Refresh dependency locks

After changing a version range in `server/requirements.txt` or `client/requirements.txt`, regenerate the lock files and rebuild the environment:

```bash
bash scripts/relock_python_deps.sh
bash scripts/setup_python_env.sh --recreate
```

`server/requirements.lock` and `client/requirements.lock` pin the exact versions every install uses. The matching `requirements.txt` files hold the allowed version ranges and are read only when the locks are regenerated. `requirements-dev.txt` adds the development tools, `requirements-test.txt` combines everything the test suite needs, and `pyproject.toml` configures the tools but pins no dependencies.

---

## 9. Reset local dev state

Interactive:

```bash
bash scripts/reset_dev_state.sh
```

Non-interactive:

```bash
bash scripts/reset_dev_state.sh --yes
```

This removes:

```text
server/riskapp.db
~/.riskapp/client.sqlite3
```

---

## 10. Environment variables reference

Every setting RiskApp reads is listed here. The server reads them from its environment, and the development launcher also loads them from `.env`.

### Server

| Variable | Default | Notes |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite+pysqlite:///./riskapp.db` | Server database URL |
| `ENV` | `development` | One of `development`, `test`, or `production`; invalid values stop startup |
| `SECRET_KEY` | unset | Random JWT signing key; required and at least 32 characters in every environment |
| `TOKEN_HASH_KEY` | unset | Separate random HMAC key for stored refresh/password-reset tokens; required and at least 32 characters in every environment |
| `ACCESS_TOKEN_MINUTES` | `15` | Access-token lifetime |
| `REFRESH_TOKEN_DAYS` | `30` | Refresh-token lifetime |
| `REFRESH_TOKEN_REUSE_GRACE_SECONDS` | `30` | One-time recovery window for a rotated token whose response was lost; `0` disables recovery |
| `LOGIN_RATE_LIMIT_PER_MINUTE` | `10` | Per-IP-and-email login attempts in the configured window |
| `LOGIN_IP_RATE_LIMIT_PER_MINUTE` | `50` | Aggregate login attempts allowed from one client IP |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | `60` | Sliding window shared by both login limits |
| `AUTO_CREATE_SCHEMA` | dev `1`, production `0` | Use explicit migrations in production |
| `ENFORCE_HTTPS` | production `1` | Reject non-HTTPS requests |
| `TRUST_X_FORWARDED_PROTO` | `0` | Enable only behind a configured trusted proxy |
| `ALLOWED_HOSTS` | dev `*`, production required | Comma-separated accepted Host values |
| `INITIAL_SUPERUSER_EMAIL` | unset | Optional create-only bootstrap superadmin email; existing accounts are never modified |
| `INITIAL_SUPERUSER_PASSWORD` | unset | Password used only when creating the bootstrap account |
| `CORS_ORIGINS` | unset | Comma-separated allowed origins |
| `MAX_REQUEST_BODY_BYTES` | `2097152` | Maximum declared or streamed request body |
| `RISKAPP_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |
| `RISKAPP_LOG_FORMAT` | `plain` | `plain` for local use or newline-delimited `json` for log collectors |
| `PASSWORD_RESET_RETURN_TOKEN` | `0` | Development/test only; forbidden in production |
| `RETENTION_DAYS` | `180` | Default age limit for the `/admin` prune endpoint |
| `SYNC_RECEIPT_RETENTION_DAYS` | `365` | Sync receipts younger than this are never pruned |
| `MAX_SYNC_PULL_PER_ENTITY` | `5000` | Sync pull cap |
| `SYNC_PUSH_EXPUNGE_EVERY` | `200` | Sync push housekeeping interval |
| `RISKAPP_HOST` | `127.0.0.1` | Address the API listens on; `127.0.0.1` keeps it reachable only from this machine |
| `RISKAPP_PORT` | `8000` | Port the API listens on |
| `RISKAPP_RELOAD` | on in development | Restart on code changes when started with `python -m riskapp_server`, the launcher always reloads |

`SECRET_KEY` signs access tokens. `TOKEN_HASH_KEY` hashes refresh and password-reset tokens before they are stored, so rotating the signing key does not invalidate them. Generate the two independently and keep both in the deployment's secret manager. Rotating `TOKEN_HASH_KEY` invalidates existing refresh and password-reset tokens.

### Advanced server settings

The defaults suit most setups. These tune the password policy, performance and internal limits.

| Variable | Default | Notes |
| --- | --- | --- |
| `ALGORITHM` | `HS256` | JWT signing algorithm: `HS256`, `HS384` or `HS512` |
| `PASSWORD_MIN_LENGTH` | `12` | Minimum password length, 8 to 128 |
| `PASSWORD_MAX_LENGTH` | `128` | Maximum password length, up to 1024 |
| `PASSWORD_REQUIRE_UPPER` | `1` | Require an uppercase letter |
| `PASSWORD_REQUIRE_LOWER` | `1` | Require a lowercase letter |
| `PASSWORD_REQUIRE_DIGIT` | `1` | Require a digit |
| `PASSWORD_REQUIRE_SYMBOL` | `1` | Require a symbol |
| `PASSWORD_RESET_TOKEN_MINUTES` | `15` | Lifetime of a password-reset token |
| `PASSWORD_RESET_RATE_LIMIT_PER_HOUR` | `5` | Password-reset requests allowed per client IP and email address |
| `RATE_LIMIT_MAX_KEYS` | `10000` | Most clients the in-memory rate limiters track at once |
| `DB_POOL_SIZE` | `5` | Database connection pool size; not used with SQLite |
| `DB_MAX_OVERFLOW` | `10` | Extra connections allowed beyond the pool; not used with SQLite |
| `DB_POOL_RECYCLE` | `1800` | Seconds before a pooled connection is replaced; not used with SQLite |
| `DB_STATEMENT_TIMEOUT_MS` | `30000` | PostgreSQL statement timeout; `0` disables it |
| `GZIP_ENABLED` | `1` | Compress responses |
| `GZIP_MINIMUM_SIZE` | `1024` | Smallest response, in bytes, that gets compressed |
| `SNAPSHOT_INSERT_CHUNK` | `1000` | Rows written per batch when saving a score snapshot |

### Docker Compose

| Variable | Default | Notes |
| --- | --- | --- |
| `RISKAPP_HOST_ADDR` | `127.0.0.1` | Host address the API container is published on |
| `RISKAPP_HOST_PORT` | `8000` | Host port the API container is published on |

Inside the container the API listens on `0.0.0.0`, which is needed for Docker's port forwarding. It is published only on `RISKAPP_HOST_ADDR`.

### Client

| Variable | Default | Notes |
| --- | --- | --- |
| `RISKAPP_URL` | `http://localhost:8000`; the launcher sets `http://127.0.0.1:8000` | Server URL used by the client |
| `RISKAPP_ALLOW_HTTP` | unset | Set to `1` for local plain HTTP |
| `RISKAPP_LOCAL_DB` | `~/.riskapp/client.sqlite3` | Local SQLite cache |
| `RISKAPP_EMAIL` | unset | Optional login prefill/automation |
| `RISKAPP_PASSWORD` | unset | Optional login prefill/automation |
| `RISKAPP_LOG_LEVEL` | `INFO` | Python log level |
| `RISKAPP_AUTO_SYNC_INTERVAL_SECONDS` | `60` | Periodic background-sync interval; `0` disables it |
| `RISKAPP_AUTO_SYNC_MAX_BACKOFF_SECONDS` | `300` | Maximum retry delay after transient sync/reconnect failures |
