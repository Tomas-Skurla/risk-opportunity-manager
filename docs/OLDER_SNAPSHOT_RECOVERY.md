# Demo: recovery after restoring earlier server data

An **older snapshot** means earlier database contents from the same application and schema version. It does not mean using an old Alembic revision with new code.

For example:

| Point in the demo | Server | Existing client |
| --- | --- | --- |
| Backup taken | Risk version 1, title `At backup` | Synced with that server |
| Later work synced | Risk version 2; a second risk exists | Both changes cached; newer sync cursor |
| Further work offline | Unchanged | An edit titled `Queued offline draft` is in the outbox |
| Earlier backup restored | Risk version 1; second risk absent | Still holds later data, cursor, and offline edit |

The server restore succeeds, but the existing client has not travelled back in time with it. Its cursor can be ahead of the restored server, causing HTTP 400 (`snapshot_sequence precedes since_sequence`). Its queued version-2 edit can become a version conflict against restored version 1. Neither is an acknowledgement that permits discarding the queued work.

## Automated rehearsal

From the repository root, with the Python 3.14 environment active:

```bash
python -m pytest tests/server/ops/test_sqlite_backup.py \
  tests/client/integration/test_snapshot_recovery.py -q
```

All databases are temporary; these tests do not read the real server or client
database. The three client recovery cases prove that:

1. A stale cursor produces an attention-required result and preserves the local draft, its original change ID, and its conflict payload.
2. Resetting just the cursor does not remove cached entities that were created after the backup. Incremental pulls merge rows; they do not rebuild the cache.
3. A fresh client cache receives exactly the restored server data. Selected offline fields can then be re-entered with a new change ID against the restored version, while the original database and preservation copy remain unchanged.

This is an explicit manual recovery strategy for the demo, not automatic rollback detection or bulk migration of every client's outbox.

## Manual Windows demo

Use disposable demo data and keep the same private `.env` keys throughout.
Follow [backup and restore](BACKUP_RESTORE.md) for the server commands.

1. Create a project and a risk titled `At backup`. Sync the client successfully, then create a server backup.
2. Change the title to `Accepted after backup`, sync, then create and sync another risk titled `Exists only after backup`.
3. Stop the server. Edit the first risk offline to `Queued offline draft` and change its probability/impact. Record these selected fields and confirm there is queued work. Close every client instance before preserving its database.
4. Preserve the original client database. The default is `%USERPROFILE%\.riskapp\client.sqlite3`; use your configured `RISKAPP_LOCAL_DB` path if different. Make a separately named copy in the protected backup directory. Copy a closed database only: if `-wal`, `-shm`, or `-journal` sidecars remain, find the remaining owner and retain the whole set instead of copying the main file alone or deleting sidecars.
5. Restore the earlier server backup with every API process stopped, then restart the API using the same keys. The original client and its preservation copy remain untouched.
6. Start the client with a **new, unused** cache path and automatic sync disabled. From the repository root, in Git Bash:

   ```bash
   mkdir -p ../riskapp-backups
   export RISKAPP_LOCAL_DB="$(python -c 'from pathlib import Path; print((Path.cwd().parent / "riskapp-backups/client-recovered.sqlite3").as_posix())')"
   export RISKAPP_AUTO_SYNC_INTERVAL_SECONDS=0
   bash scripts/run_client_dev.sh
   ```

   Or in PowerShell, with the environment active:

   ```powershell
   New-Item -ItemType Directory -Force ../riskapp-backups | Out-Null
   $env:RISKAPP_LOCAL_DB = Join-Path (Resolve-Path ../riskapp-backups).Path "client-recovered.sqlite3"
   $env:RISKAPP_AUTO_SYNC_INTERVAL_SECONDS = "0"
   Push-Location client
   python -m riskapp_client.app
   Pop-Location
   ```

   Use a dedicated terminal for this recovery session. The filename must be new for each rehearsal; an existing cache is not a fresh start.
7. Log in, select the recovered project, and sync manually. Verify the title is `At backup` and the later risk is absent. Login and project membership should still work because they existed in the backup.
8. Decide which later work to recover. Re-enter the recorded `Queued offline draft` fields into the restored risk, then sync. The new edit is based on the restored version. Re-create later entities only if explicitly desired; do not blindly import old payloads or replay old change IDs.
9. Close the recovery client and retain the original database/copy until the selected recovery is verified. Future demo launches must use the recovered cache path explicitly. The old default cache must not automatically reconnect to this restored server.

The automatic tests exercise one risk edit, a later cached risk, and cursor rollback. They do not claim automated recovery of every entity, attachment, local project, or dependency. Actions and assessments require checking their parent relationships when manually recovering selected work.

## Known limits

- The snapshot is the server's recovery boundary: later acknowledged server writes are absent unless recovered separately.
- The outbox contains pending work, not a complete history of all acknowledged changes. Later data may also survive only in the original client cache.
- Keeping that cache preserves evidence and editable values; it does not itself merge them into the restored server.
- A fresh cache avoids stale cursors and leftover records. Human selection and re-entry avoid silently replacing restored data with every later cached value.
- Clearing client databases or only resetting sync cursors is not this recovery procedure.
