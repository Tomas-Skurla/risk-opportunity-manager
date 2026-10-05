# RiskApp Server

FastAPI backend for RiskApp.

## Overview

- Risks and opportunities CRUD.
- Actions and assessments.
- Matrix, snapshot, and Help Desk endpoints.
- Offline sync for risks, opportunities, actions, assessments, and Help Desk tickets.
- Transactional per-project change sequences provide commit-safe incremental pulls.
- JWT auth and project/global role checks.
- Startup bootstrap for a global superadmin.

## Running the server

The [setup guide](../docs/SETUP_GUIDE.md#6-start-the-server) covers installing, starting and health-checking the server, with or without the launcher script. The API then runs at `http://127.0.0.1:8000`, with interactive documentation at `/docs`.

## Accounts and login

### Superadmin bootstrap

`scripts/dev-init.sh` fills `INITIAL_SUPERUSER_EMAIL` and
`INITIAL_SUPERUSER_PASSWORD` in `.env`. Read the generated password there and change the email before the first start if needed. To skip account creation, leave both settings blank. Deployments can supply their own values directly.

On startup, the server creates that user only when the email is absent. If the account already exists, bootstrap leaves its password, active state, and superuser flag unchanged.

### Regular registration

The `/register` endpoint creates a regular active user, not a global superadmin.

```bash
curl -X POST http://127.0.0.1:8000/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"<your email here>","password":"<your password here>"}'
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

## Global administration

Operations reserved for superusers live under `/admin/`, and the admin router requires a superuser for every route in it:

- `DELETE /admin/projects/{project_id}` deletes a project and all its data
- `POST /admin/projects/{project_id}/maintenance/prune` removes old audit history
- `POST /admin/users/{user_id}/deactivate`, `.../activate`, `.../set-password`

A gateway can therefore keep global administration off the public entrance with one path rule, while the API still checks the superuser flag itself. Project administrators manage their own projects through the ordinary routes.

## Audit retention

Superusers can delete old audit-log and sync-receipt rows for one project. Use the
`access_token` returned by the login call above:

```bash
curl -X POST "http://127.0.0.1:8000/admin/projects/$PROJECT_ID/maintenance/prune?days=180" \
  -H "Authorization: Bearer $TOKEN"
```

`days` defaults to `RETENTION_DAYS` (180) and is limited to 1-3650. Sync receipts are kept for at least `SYNC_RECEIPT_RETENTION_DAYS` (365) so replayed pushes stay idempotent. Project administrators get HTTP 403: they cannot shorten their own project's audit trail. To run this on a schedule, log in within the same job, because access tokens expire after `ACCESS_TOKEN_MINUTES`.

## Configuration

Every setting is listed in the [configuration reference](../docs/SETUP_GUIDE.md#10-environment-variables-reference).

Every HTTP response includes `X-Request-ID`. A valid incoming `X-Request-ID` is preserved; otherwise the API generates one. RiskApp application logs include the same ID, HTTP method, path, status, and duration without recording query strings, authorization headers, or request bodies. Set `RISKAPP_LOG_FORMAT=json` for structured production logs; Uvicorn's own process logs remain independently configured by Uvicorn.

Password hashing, tokens and the rest of the security model are described in [ARCHITECTURE.md](../docs/ARCHITECTURE.md#6-security-model).

## Scoring notes

- Probability and impact use a `1..5` scale.
- Score is `probability * impact`.
- If per-dimension impacts are present, effective `impact` is recalculated from the maximum provided impact dimension.
