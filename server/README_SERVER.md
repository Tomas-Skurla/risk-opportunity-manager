# RiskApp Server

FastAPI backend for RiskApp.

## Overview

- Risks and opportunities CRUD.
- Actions and assessments.
- Matrix, snapshot, and Help Desk endpoints.
- Offline sync for risks, opportunities, actions, assessments, and Help Desk tickets.
- Transactional per-project change sequences provide commit-safe incremental pulls; timestamp watermarks remain compatible with older clients.
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

On startup, the server creates that user only when the email is absent. If the account already exists, bootstrap leaves its password, active state, and superuser flag unchanged.

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
Every REST update of a risk, opportunity, action, assessment, or Help Desk ticket must include the current `base_version`. A missing version is rejected with HTTP 422; a stale version returns HTTP 409 and the server's current version.

## Configuration

Common settings:

| Variable | Default | Notes |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite+pysqlite:///./riskapp.db` | Server database URL |
| `ENV` | `development` | One of `development`, `test`, or `production`; invalid values stop startup |
| `SECRET_KEY` | `change-me` | Required outside local dev unless insecure default is explicitly allowed |
| `TOKEN_HASH_KEY` | unset | HMAC key for stored refresh/password-reset tokens; required and at least 32 characters in production |
| `ALLOW_INSECURE_DEFAULT_SECRET` | unset | Use `1` only for local development |
| `ACCESS_TOKEN_MINUTES` | `15` | Access-token lifetime; legacy alias: `TOKEN_MINUTES` |
| `REFRESH_TOKEN_DAYS` | `30` | Refresh-token lifetime |
| `REFRESH_TOKEN_REUSE_GRACE_SECONDS` | `30` | One-time lost-response recovery window; `0` disables recovery |
| `LOGIN_RATE_LIMIT_PER_MINUTE` | `10` | Per-IP-and-email login attempts in the configured window |
| `LOGIN_IP_RATE_LIMIT_PER_MINUTE` | `50` | Aggregate login attempts allowed from one client IP |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | `60` | Sliding window shared by both login limits |
| `AUTO_CREATE_SCHEMA` | dev `1`, production `0` | Use explicit migrations in production |
| `ENFORCE_HTTPS` | production-enabled | HTTPS enforcement |
| `TRUST_X_FORWARDED_PROTO` | `0` | Enable only behind a configured trusted proxy |
| `ALLOWED_HOSTS` | dev `*`, production required | Comma-separated accepted Host values |
| `INITIAL_SUPERUSER_EMAIL` | unset | Optional create-only bootstrap superadmin email; existing accounts are never modified |
| `INITIAL_SUPERUSER_PASSWORD` | unset | Password used only when creating the bootstrap account |
| `CORS_ORIGINS` | unset | Comma-separated allowed origins |
| `MAX_REQUEST_BODY_BYTES` | `2097152` | Maximum declared or streamed request body |
| `RISKAPP_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |
| `RISKAPP_LOG_FORMAT` | `plain` | `plain` for local use or newline-delimited `json` for log collectors |
| `PASSWORD_RESET_RETURN_TOKEN` | `0` | Development/test only; forbidden in production |
| `MAX_SYNC_PULL_PER_ENTITY` | `5000` | Sync pull cap |
| `SYNC_PUSH_EXPUNGE_EVERY` | `200` | Sync push housekeeping interval; misspelled `SYNC_PUSH_EXUNGE_EVERY` remains a deprecated fallback |

`SECRET_KEY` signs access JWTs. `TOKEN_HASH_KEY` hashes opaque refresh and password-reset tokens before database storage, so routine JWT-key rotation does not invalidate those tokens. Generate the two values independently for new deployments.

For an existing deployment, first set `TOKEN_HASH_KEY` to the current `SECRET_KEY` value and deploy this version. You may then rotate `SECRET_KEY` without invalidating stored refresh/password-reset token hashes. Changing `TOKEN_HASH_KEY` itself invalidates all outstanding refresh and reset tokens.

Every HTTP response includes `X-Request-ID`. A valid incoming `X-Request-ID` is preserved; otherwise the API generates one. RiskApp application logs include the same ID, HTTP method, path, status, and duration without recording query strings, authorization headers, or request bodies. Set `RISKAPP_LOG_FORMAT=json` for structured production logs; Uvicorn's own process logs remain independently configured by Uvicorn.

New account passwords are hashed with Argon2id using 19 MiB of memory, two iterations, and one lane. Existing `pbkdf2_sha256` hashes continue to verify and are replaced with Argon2id only after that user successfully logs in. The `PBKDF2_ITERS` setting is retained for compatibility but no longer controls new password hashes.

## Scoring notes

- Probability and impact use a `1..5` scale.
- Score is `probability * impact`.
- If per-dimension impacts are present, effective `impact` is recalculated from the maximum provided impact dimension.
