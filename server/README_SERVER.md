# RiskApp Server

FastAPI backend for RiskApp.

## Overview

- Risks and opportunities CRUD.
- Actions and assessments.
- Matrix, snapshot, and Help Desk endpoints.
- Offline sync for risks, opportunities, actions, assessments, and Help Desk tickets.
- JWT auth and project/global role checks.
- Startup bootstrap for a global superadmin.

## Recommended install

From the repository root:

```bash
bash scripts/setup_python_env.sh
```

The server dependencies are installed from:

```text
server/requirements.lock
```

Use `server/requirements.txt` only as the source/range file when regenerating the lock with `scripts/relock_python_deps.sh`.

## Run locally

From the repository root:

```bash
RESET_SERVER_DB=1 bash scripts/run_server_dev.sh
```

Without resetting the database:

```bash
bash scripts/run_server_dev.sh
```

The development script sets:

```text
ALLOW_INSECURE_DEFAULT_SECRET=1
INITIAL_SUPERUSER_EMAIL=admin@example.com
INITIAL_SUPERUSER_PASSWORD=SuperHeslo123!
```

The server runs at:

```text
http://127.0.0.1:8000
```

## Direct manual run

If you need to run without the helper script:

```bash
cd /path/to/repo
source .venv/bin/activate
rm -f server/riskapp.db
cd server
ALLOW_INSECURE_DEFAULT_SECRET=1 \
INITIAL_SUPERUSER_EMAIL=admin@example.com \
INITIAL_SUPERUSER_PASSWORD='SuperHeslo123!' \
uvicorn riskapp_server.main.app:app --reload --host 127.0.0.1 --port 8000
```

## Health check

```bash
curl -s -o /tmp/riskapp-health.json -w "HTTP %{http_code}\n" http://127.0.0.1:8000/health
cat /tmp/riskapp-health.json
```

Expected:

```text
HTTP 200
{"status":"ok","db":"ok"}
```

## First run: superadmin vs regular users

### Superadmin bootstrap

Use these environment variables before startup:

```text
INITIAL_SUPERUSER_EMAIL=admin@example.com
INITIAL_SUPERUSER_PASSWORD=SuperHeslo123!
```

On startup, the server creates that user if missing or promotes the existing user to global superadmin.

### Regular registration

The `/register` endpoint creates a regular active user, not a global superadmin.

```bash
curl -X POST http://127.0.0.1:8000/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"user@example.com","password":"UserHeslo123!"}'
```

### Login

```bash
curl -X POST http://127.0.0.1:8000/login \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'username=admin@example.com&password=SuperHeslo123%21'
```

## Help Desk endpoints

The server exposes Help Desk CRUD routes per project:

- `GET /projects/{project_id}/helpdesk/tickets`
- `POST /projects/{project_id}/helpdesk/tickets`
- `PATCH /projects/{project_id}/helpdesk/tickets/{ticket_id}`
- `DELETE /projects/{project_id}/helpdesk/tickets/{ticket_id}`

Help Desk tickets are included in sync push/pull for server-backed projects.

## Configuration

Common settings:

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite+pysqlite:///./riskapp.db` | Server database URL |
| `ENV` | `development` | Set to `production` in deployments |
| `SECRET_KEY` | `change-me` | Required outside local dev unless insecure default is explicitly allowed |
| `ALLOW_INSECURE_DEFAULT_SECRET` | unset | Use `1` only for local development |
| `ACCESS_TOKEN_MINUTES` | `15` | Access-token lifetime; legacy alias: `TOKEN_MINUTES` |
| `REFRESH_TOKEN_DAYS` | `30` | Refresh-token lifetime |
| `AUTO_CREATE_SCHEMA` | dev `1`, production `0` | Use explicit migrations in production |
| `ENFORCE_HTTPS` | production-enabled | HTTPS enforcement |
| `TRUST_X_FORWARDED_PROTO` | `0` | Enable only behind a configured trusted proxy |
| `ALLOWED_HOSTS` | dev `*`, production required | Comma-separated accepted Host values |
| `INITIAL_SUPERUSER_EMAIL` | unset | Optional bootstrap superadmin email |
| `INITIAL_SUPERUSER_PASSWORD` | unset | Optional bootstrap superadmin password |
| `CORS_ORIGINS` | unset | Comma-separated allowed origins |
| `MAX_REQUEST_BODY_BYTES` | `2097152` | Maximum declared or streamed request body |
| `PASSWORD_RESET_RETURN_TOKEN` | `0` | Development/test only; forbidden in production |
| `MAX_SYNC_PULL_PER_ENTITY` | `5000` | Sync pull cap |
| `SYNC_PUSH_EXUNGE_EVERY` | `200` | Sync push housekeeping interval |

## Scoring notes

- Probability and impact use a `1..5` scale.
- Score is `probability * impact`.
- If per-dimension impacts are present, effective `impact` is recalculated from the maximum provided impact dimension.
