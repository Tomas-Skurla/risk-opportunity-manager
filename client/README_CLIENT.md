# RiskApp Desktop Client

PySide6 desktop client for RiskApp.

## Overview

- Local SQLite cache with an outbox.
- Manual sync with the server.
- Sidebar views for Risks, Opportunities, Matrix, Top history, Actions, Assessments, Members, and Help Desk.
- Online login, account registration, offline-as-user mode, and fully local anonymous mode.
- Qt/PySide runtime diagnostics through `scripts/diagnose_qt_runtime.sh`.

## Recommended install

From the repository root:

```bash
bash scripts/setup_os_prereqs.sh --desktop
bash scripts/setup_python_env.sh
bash scripts/diagnose_qt_runtime.sh
```

The client dependencies are installed from:

```text
client/requirements.lock
```

Use `client/requirements.txt` only as the source/range file when regenerating the lock with `scripts/relock_python_deps.sh`.

## Run

From the repository root:

```bash
RESET_CLIENT_DB=1 bash scripts/run_client_dev.sh
```

Without resetting the local database:

```bash
bash scripts/run_client_dev.sh
```

The script sets local-development defaults:

```text
RISKAPP_ALLOW_HTTP=1
RISKAPP_URL=http://127.0.0.1:8000
RISKAPP_API_BASE_URL=http://127.0.0.1:8000
```

## Direct manual run

If you need to run without the helper script:

```bash
cd /path/to/repo
source .venv/bin/activate
cd client
RISKAPP_ALLOW_HTTP=1 RISKAPP_URL=http://127.0.0.1:8000 python -m riskapp_client.app
```

## First run

On first launch, the login dialog lets you:

- sign in with an existing account;
- register a new account on the server;
- work offline as a known user when the server is unavailable;
- work fully local with no account and no sync.

You can also create an account directly through the server API:

```bash
curl -X POST http://127.0.0.1:8000/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"user@example.com","password":"UserHeslo123!"}'
```

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `RISKAPP_URL` | `http://127.0.0.1:8000` | Server URL used by the client |
| `RISKAPP_API_BASE_URL` | same as `RISKAPP_URL` | API base URL override |
| `RISKAPP_EMAIL` | unset | Optional login prefill/automation |
| `RISKAPP_PASSWORD` | unset | Optional login prefill/automation |
| `RISKAPP_LOCAL_DB` | `~/.riskapp/client.sqlite3` | Local SQLite cache |
| `RISKAPP_ALLOW_HTTP` | unset | Set to `1` for local HTTP development |
| `RISKAPP_LOG_LEVEL` | `INFO` | Python log level |

## Offline modes

| Mode | Account? | Server required? | Sync later? | Sidebar label |
|---|---:|---:|---:|---|
| Online | yes | yes at login | yes | owner email if known |
| Offline as known user | known identity | no | yes, after online login + **Sync Now** | `(offline, will sync)` |
| Fully local anonymous | no | no | no | `(local only)` |

Fully local anonymous data never syncs to the server.

## Qt/PySide diagnostics

If the client fails to import or launch with missing native libraries, run:

```bash
bash scripts/diagnose_qt_runtime.sh
```

Common Debian/Ubuntu missing-library fixes include:

```bash
sudo apt install -y libglib2.0-0
# or, on newer t64-based releases:
sudo apt install -y libglib2.0-0t64
```

For broader OS package installation, rerun:

```bash
bash scripts/setup_os_prereqs.sh --desktop
```

## Notes

- Server-side authorization is authoritative.
- Client-side role checks shape UI behavior only.
- Help Desk tickets are stored locally and, for server-backed projects, participate in offline-first sync.
- In **Work Fully Local** mode, Help Desk tickets remain local like the rest of the anonymous local project data.
