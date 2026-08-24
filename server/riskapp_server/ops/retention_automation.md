# Retention automation

The API exposes an admin-only maintenance endpoint for each project:

- `POST /projects/{project_id}/maintenance/prune?days=180`

In practice, the caller must have at least **project admin** access for that project.

To automate pruning without an in-app scheduler, prefer running the supplied helper script from cron, systemd, or CI. This is safer than storing a bearer token because access tokens are short-lived by default.

## Recommended: helper script

Set these environment variables:

```bash
export RISKAPP_BASE_URL=http://127.0.0.1:8000
export RISKAPP_ADMIN_EMAIL=admin@example.com
export RISKAPP_ADMIN_PASSWORD='...'
```

Run the job:

```bash
python -m riskapp_server.ops.prune_job <PROJECT_ID> 180
```

The script:

- logs in via `/login`
- obtains a fresh access token
- calls `/projects/{project_id}/maintenance/prune?days=180`

## Example: cron (Linux)

```cron
15 3 * * * cd /path/to/server && /usr/bin/env   RISKAPP_BASE_URL=http://127.0.0.1:8000   RISKAPP_ADMIN_EMAIL=admin@example.com   RISKAPP_ADMIN_PASSWORD='replace-me'   /usr/bin/python3 -m riskapp_server.ops.prune_job <PROJECT_ID> 180   >>/var/log/riskapp_prune.log 2>&1
```

## Example: systemd timer

Create a oneshot service that runs `python -m riskapp_server.ops.prune_job ...`, then pair it with a timer unit that runs daily.

## Alternative: direct HTTP call

If you prefer `curl`, mint a **fresh** token in the same scheduled job and then call the prune endpoint. Do not assume a token created earlier will still be valid later.

## Index migration

Alembic-managed databases receive these indexes from the baseline migration. Run
`riskapp_server/ops/sql/001_add_composite_indexes.sql` only for a legacy database
created before Alembic was introduced, and verify that database before stamping it
at revision `0001`. The older `001_add_indexes.sql` file is kept only for backward
compatibility.
