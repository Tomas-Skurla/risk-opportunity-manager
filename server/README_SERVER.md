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
./scripts/dev-init.sh
RESET_SERVER_DB=1 bash scripts/run_server_dev.sh
```

Without resetting the database:

```bash
bash scripts/run_server_dev.sh
```

The setup script generates private keys and a random administrator password in
the Git-ignored `.env`, preserving an existing file. The development launcher
loads `.env`; exported settings take precedence. `RESET_SERVER_DB=1` deletes the
existing development database before startup.

The server runs at:

```text
http://127.0.0.1:8000
```

## Direct manual run

If you need to run without the helper script:

```bash
cd /path/to/repo
source .venv/bin/activate
./scripts/dev-init.sh
rm -f server/riskapp.db
cd server
uvicorn riskapp_server.main.app:app --env-file ../.env \
  --reload --host 127.0.0.1 --port 8000
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

`scripts/dev-init.sh` fills `INITIAL_SUPERUSER_EMAIL` and
`INITIAL_SUPERUSER_PASSWORD` in `.env`. Read the generated password there and
change the email before the first start if needed. To skip account creation,
leave both settings blank. Deployments can supply their own values directly.

On startup, the server creates that user only when the email is absent. If the account already exists, bootstrap leaves its password, active state, and superuser flag unchanged.

### Regular registration

The `/register` endpoint creates a regular active user, not a global superadmin.

```bash
curl -X POST http://127.0.0.1:8000/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"user@example.com","password":"UserHeslo123!"}'
```

### Login

Enter the credentials from `.env`, or the account's current password if it has
already been changed:

```bash
read -r -p 'Email: ' RISKAPP_LOGIN_EMAIL
read -r -s -p 'Password: ' RISKAPP_LOGIN_PASSWORD
printf '\n'
curl -X POST http://127.0.0.1:8000/login \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode "username=$RISKAPP_LOGIN_EMAIL" \
  --data-urlencode "password=$RISKAPP_LOGIN_PASSWORD"
unset RISKAPP_LOGIN_PASSWORD
```

## Help Desk endpoints

The server exposes Help Desk CRUD routes per project:

- `GET /projects/{project_id}/helpdesk/tickets`
- `POST /projects/{project_id}/helpdesk/tickets`
- `PATCH /projects/{project_id}/helpdesk/tickets/{ticket_id}`
- `DELETE /projects/{project_id}/helpdesk/tickets/{ticket_id}`

Help Desk tickets are included in sync push/pull for server-backed projects.
Every REST update of a risk, opportunity, action, assessment, or Help Desk ticket must include the current `base_version`. A missing version is rejected with HTTP 422; a stale version returns HTTP 409 and the server's current version.

## Audit retention

Superusers can delete old audit-log and sync-receipt rows for one project. Use the
`access_token` returned by the login call above:

```bash
curl -X POST "http://127.0.0.1:8000/projects/$PROJECT_ID/maintenance/prune?days=180" \
  -H "Authorization: Bearer $TOKEN"
```

`days` defaults to `RETENTION_DAYS` (180) and is limited to 1-3650. Sync receipts are
kept for at least `SYNC_RECEIPT_RETENTION_DAYS` (365) so replayed pushes stay
idempotent. Project administrators get HTTP 403: they cannot shorten their own
project's audit trail. To run this on a schedule, log in within the same job,
because access tokens expire after `ACCESS_TOKEN_MINUTES`.

## Configuration

Common settings:

| Variable | Default | Notes |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite+pysqlite:///./riskapp.db` | Server database URL |
| `ENV` | `development` | One of `development`, `test`, or `production`; invalid values stop startup |
| `SECRET_KEY` | unset | Random JWT signing key; required and at least 32 characters in every environment |
| `TOKEN_HASH_KEY` | unset | Separate random HMAC key for stored refresh/password-reset tokens; required and at least 32 characters in every environment |
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

For an existing deployment that previously omitted `TOKEN_HASH_KEY`, set it to
the existing `SECRET_KEY` before upgrading, provided that key is private and at
least 32 characters long. This preserves stored refresh/password-reset token
hashes. Keep an already configured `TOKEN_HASH_KEY` unchanged. Changing it
invalidates all outstanding refresh and reset tokens.

Missing, blank, and short keys now stop startup in development and test as well
as production. The former `ALLOW_INSECURE_DEFAULT_SECRET` setting has no effect.
Replace any previously shared demo keys with generated values; affected users
will need to log in again.

Every HTTP response includes `X-Request-ID`. A valid incoming `X-Request-ID` is preserved; otherwise the API generates one. RiskApp application logs include the same ID, HTTP method, path, status, and duration without recording query strings, authorization headers, or request bodies. Set `RISKAPP_LOG_FORMAT=json` for structured production logs; Uvicorn's own process logs remain independently configured by Uvicorn.

New account passwords are hashed with Argon2id using 19 MiB of memory, two iterations, and one lane. Existing `pbkdf2_sha256` hashes continue to verify and are replaced with Argon2id only after that user successfully logs in. The `PBKDF2_ITERS` setting is retained for compatibility but no longer controls new password hashes.

## Scoring notes

- Probability and impact use a `1..5` scale.
- Score is `probability * impact`.
- If per-dimension impacts are present, effective `impact` is recalculated from the maximum provided impact dimension.
