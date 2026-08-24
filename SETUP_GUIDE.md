# RiskApp — Setup Guide

This guide describes the recommended local setup using the repository scripts. The scripts keep setup repeatable across Linux distributions and macOS/Homebrew where possible.

## Prerequisites

- Python 3.11 through 3.14. Python 3.14 is supported by the current lock files.
- A shell capable of running Bash scripts.
- Two terminal windows for running the server and client.
- For the desktop GUI, install OS-level Qt/X11 runtime libraries through `scripts/setup_os_prereqs.sh`.

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

For a desktop development machine:

```bash
bash scripts/setup_os_prereqs.sh --desktop
```

For server/API-only testing:

```bash
bash scripts/setup_os_prereqs.sh --server-only
```

For headless GUI smoke testing:

```bash
bash scripts/setup_os_prereqs.sh --headless-gui
```

For everything, including LibreOffice Calc for CSV manual checks:

```bash
bash scripts/setup_os_prereqs.sh --all
```

The script is best-effort and supports common package managers including `apt`, `dnf`, `yum`, `pacman`, `zypper`, `apk`, and `brew`. Package names still vary by distro; if the Qt GUI fails, run the diagnostic script in step 4.

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

The script accepts Python 3.11 through 3.14. It creates `.venv`, installs:

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

This runs:

```text
scripts/check_migrations.py
scripts/test.sh
scripts/lint.sh
python -m pip check
```

If Ruff reports safe fixable issues, run:

```bash
bash scripts/check_project.sh --fix
bash scripts/check_project.sh
```

---

## 6. Start the server

Use Terminal 1:

```bash
RESET_SERVER_DB=1 bash scripts/run_server_dev.sh
```

This starts Uvicorn with local-development defaults:

```text
ALLOW_INSECURE_DEFAULT_SECRET=1
INITIAL_SUPERUSER_EMAIL=admin@example.com
INITIAL_SUPERUSER_PASSWORD=SuperHeslo123!
```

The server runs at:

```text
http://127.0.0.1:8000
```

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

Do not use `ALLOW_INSECURE_DEFAULT_SECRET=1` outside local development.

For staging or production, run the migration job once before starting API
workers. `DATABASE_URL` is intentionally required:

```bash
source .venv/bin/activate
export DATABASE_URL='sqlite+pysqlite:////absolute/path/to/riskapp.db'
bash scripts/migrate_server.sh
```

Keep `AUTO_CREATE_SCHEMA=0` in deployed environments. Existing databases made
with automatic schema creation must be backed up and verified before stamping
the baseline revision; do not blindly stamp them.

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
Email: admin@example.com
Password: SuperHeslo123!
```

---

## 8. Optional one-shot bootstrap

After each individual script has been tested, you can use the orchestrator:

```bash
bash scripts/bootstrap_dev.sh --desktop
```

If OS packages are already installed:

```bash
bash scripts/bootstrap_dev.sh --skip-os-prereqs
```

If dependency ranges changed and you need fresh locks:

```bash
bash scripts/bootstrap_dev.sh --skip-os-prereqs --relock
```

Then start the server and client separately:

```bash
RESET_SERVER_DB=1 bash scripts/run_server_dev.sh
RESET_CLIENT_DB=1 bash scripts/run_client_dev.sh
```

---

## 9. Login dialog

The login dialog has four options:

- **OK** — login to the server with email and password.
- **Register new account…** — create a regular server account.
- **Work Fully Local (no account, no sync)** — work without an account. Data stays on this machine and does not sync.
- **Cancel** — quit the application.

If the server is unreachable after clicking **OK**, a **Server Unavailable** dialog appears with:

- **Work Offline as user@example.com (will sync later)** — offline mode associated with that identity. Data can sync after the server is available and you click **Sync Now**.
- **Work Fully Local (no account, no sync)** — anonymous local mode; data never syncs.
- **Quit** — exit.

---

## 10. Register a regular user

### From the client

1. Launch the client.
2. Click **Register new account…**.
3. Fill in:
   - Server URL: `http://127.0.0.1:8000`
   - Email: `user@example.com`
   - Password: `UserHeslo123!`
4. Click **OK**.

### Via curl

```bash
curl -X POST http://127.0.0.1:8000/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"user@example.com","password":"UserHeslo123!"}'
```

Registration creates a regular user, not a global superadmin.

---

## 11. Add a regular user to a project

1. Log in as `admin@example.com`.
2. Create or select a project.
3. Open the **Members** tab.
4. Enter `user@example.com` and choose a role.
5. Click **Add/Update**.

The user can now log in and see that project.

---

## 12. Delete a project

Only global superadmins can delete projects.

1. Log in as `admin@example.com`.
2. Select the project in the sidebar.
3. Click **Delete Project**.
4. Confirm the warning dialog.

This permanently deletes the project and its server-side data.

---

## 13. Offline modes

### Work Fully Local

- No account or server required.
- Data is stored in `~/.riskapp/client.sqlite3`.
- Projects show `(local only)`.
- Data never syncs to the server.

### Work Offline as user@example.com

- Intended for a known identity when the server is unavailable.
- Data is stored locally with that identity.
- Projects show `(offline, will sync)`.
- After the server is available, log in online and click **Sync Now**.
- If a project name already exists on the server, a numeric suffix is added, for example `Test Project (2)`.

### Online with offline fallback

- Normal online login.
- Changes are written locally and queued in the outbox.
- If the server goes down mid-session, local work can continue.
- Use **Sync Now** after reconnecting.

---

## 14. Role hierarchy

| Role | Scope | Typical permissions |
|---|---|---|
| **superadmin** | global | Full access, project deletion, all projects, global admin operations |
| **admin** | per project | Manage project members, edit/delete project data, snapshots |
| **manager** | per project | Manage project content and snapshots |
| **member** | per project | Create/edit risks, opportunities, actions, assessments, and Help Desk tickets |
| **viewer** | per project | Read-only access |

Superadmin is set at server startup through `INITIAL_SUPERUSER_EMAIL` and `INITIAL_SUPERUSER_PASSWORD`. Project roles are assigned in the **Members** tab.

---

## 15. Available tabs

| Tab | Description |
|---|---|
| Risks | Risk register with qualitative probability × impact scoring |
| Opportunities | Opportunity register with qualitative probability × impact scoring |
| Matrix | Probability × impact matrix view |
| Top history | Snapshot tracking of top-N items over time |
| Actions | Mitigation, contingency, and exploit actions |
| Assessments | Per-user scoring of risks and opportunities |
| Members | Project member and role management |
| Help Desk | Per-project support tickets with offline-first sync for server-backed projects |

---

## 16. Sidebar project labels

| Label | Meaning |
|---|---|
| `Project Name  (admin@example.com)` | Server project with owner email |
| `Project Name  (offline, will sync)` | Local project associated with an identity; can sync later |
| `Project Name  (local only)` | Anonymous local project; never syncs |
| `Project Name` | Server project with owner unknown |

---

## 17. Reset local dev state

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

## 18. Environment variables reference

### Server

| Variable | Default / example | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite+pysqlite:///./riskapp.db` | Server database URL |
| `ENV` | `development` | Use `production` in deployments |
| `SECRET_KEY` | `change-me` | Set a real secret outside local development |
| `ALLOW_INSECURE_DEFAULT_SECRET` | unset | Use `1` only for local development |
| `INITIAL_SUPERUSER_EMAIL` | unset | Optional startup superadmin email |
| `INITIAL_SUPERUSER_PASSWORD` | unset | Optional startup superadmin password |
| `ACCESS_TOKEN_MINUTES` | `15` | Access-token lifetime |
| `REFRESH_TOKEN_DAYS` | `30` | Refresh-token lifetime |
| `AUTO_CREATE_SCHEMA` | dev `1`, production `0` | Use explicit migrations in production |
| `ALLOWED_HOSTS` | dev `*`, production required | Comma-separated accepted Host values |
| `CORS_ORIGINS` | unset | Comma-separated allowed origins |
| `ENFORCE_HTTPS` | production `1` | Reject non-HTTPS requests |
| `TRUST_X_FORWARDED_PROTO` | `0` | Enable only behind a configured trusted proxy |
| `MAX_REQUEST_BODY_BYTES` | `2097152` | Maximum declared or streamed request body |
| `PASSWORD_RESET_RETURN_TOKEN` | `0` | Development/test only; forbidden in production |

### Client

| Variable | Default / example | Notes |
|---|---|---|
| `RISKAPP_URL` | `http://127.0.0.1:8000` | Server URL used by the client |
| `RISKAPP_API_BASE_URL` | same as `RISKAPP_URL` | API base URL override |
| `RISKAPP_ALLOW_HTTP` | unset | Set to `1` for local plain HTTP |
| `RISKAPP_LOCAL_DB` | `~/.riskapp/client.sqlite3` | Local SQLite cache |
| `RISKAPP_EMAIL` | unset | Optional login prefill/automation |
| `RISKAPP_PASSWORD` | unset | Optional login prefill/automation |
