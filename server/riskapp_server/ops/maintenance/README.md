# Maintenance automation

The server exposes a retention endpoint:

- `POST /projects/{project_id}/maintenance/prune?days=N` (project admin or superuser)

To keep DB growth under control, schedule it **externally** (cron, systemd, CI),
so you do not duplicate work across multiple app workers.

## One-off run

Set credentials for a dedicated admin-capable account:

```bash
export RISKAPP_BASE_URL=http://127.0.0.1:8000
export RISKAPP_ADMIN_EMAIL=admin@example.com
export RISKAPP_ADMIN_PASSWORD='...'
python -m riskapp_server.ops.prune_job <project_id> 180
```

The helper script logs in for each run, obtains a fresh access token, and then calls the prune endpoint.

## Cron example

See `cron.example`.

## systemd example

See the `riskapp-prune.*` unit files in this folder for a service + timer.
