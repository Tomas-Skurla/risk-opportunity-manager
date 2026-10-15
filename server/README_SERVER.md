# RiskApp Server

The FastAPI backend serves risks, opportunities, actions, assessments, the matrix, snapshots and Help Desk tickets, with JWT authentication and project roles. Offline synchronization covers risks, opportunities, actions, assessments and Help Desk tickets. Snapshot creation, history loading and member administration use online requests. The [setup guide](../docs/SETUP_GUIDE.md#3-start-the-server-and-the-client) covers starting it; the interactive API documentation is at `/docs`. [ARCHITECTURE.md](../docs/ARCHITECTURE.md) describes the sync design and the security model.


## Accounts

### Superadmin bootstrap

`scripts/dev-init.sh` fills `INITIAL_SUPERUSER_EMAIL` and `INITIAL_SUPERUSER_PASSWORD` in `.env`; change the email before the first start if you like, or clear both to skip the account. On startup the server creates that user only if the email does not exist yet. An existing account keeps its password, active state and superuser flag.

### Registration and login

`/register` creates a regular active user, never a superadmin:

```bash
curl -X POST http://127.0.0.1:8000/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"<your email here>","password":"<your password here>"}'
```

`/login` takes a form body and returns an `access_token`:

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

## API rules

- Every REST update of a risk, opportunity, action, assessment or Help Desk ticket must include the current `base_version`. A missing version gets HTTP 422, a stale one gets HTTP 409 with the server's current version.
- Help Desk tickets live under `/projects/{project_id}/helpdesk/tickets` (`GET`, `POST`, and `PATCH`/`DELETE` on `/{ticket_id}`).
- Probability and impact use a 1–5 scale, and `score = probability * impact`. When per-dimension impacts are given, `impact` is the highest of them.
- Every response carries `X-Request-ID`. A valid incoming ID is kept, otherwise the API generates one. Application logs include the same ID, method, path, status and duration, but never query strings, authorization headers or bodies. `RISKAPP_LOG_FORMAT=json` switches to structured logs.

## Global administration

Superuser-only operations live under `/admin/`, and the admin router requires a superuser for every route in it:

- `DELETE /admin/projects/{project_id}` deletes a project and all its data
- `POST /admin/projects/{project_id}/maintenance/prune` removes old audit history
- `POST /admin/users/{user_id}/deactivate`, `.../activate` and `.../set-password`

A gateway can therefore keep global administration off the public entrance with one path rule, while the API still checks the superuser flag itself. Project admins manage their own projects through the ordinary routes.

To prune one project's audit log and sync receipts, use the `access_token` from the login call:

```bash
curl -X POST "http://127.0.0.1:8000/admin/projects/$PROJECT_ID/maintenance/prune?days=180" \
  -H "Authorization: Bearer $TOKEN"
```

`days` defaults to `RETENTION_DAYS` (180) and is limited to 1–3650. Sync receipts are kept for at least `SYNC_RECEIPT_RETENTION_DAYS` (365) so resent pushes stay idempotent. Project admins get HTTP 403: they cannot shorten their own project's audit trail. A scheduled job must log in each time, because access tokens expire after `ACCESS_TOKEN_MINUTES`.

All settings are listed in the [configuration reference](../docs/SETUP_GUIDE.md#7-configuration).
