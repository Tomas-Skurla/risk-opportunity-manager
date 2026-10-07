# Server database backup and recovery

The backup command uses SQLite's online backup API, validates the resulting database, and publishes a new standalone file. It includes committed WAL data without requiring the API to stop. Restore requires every API process to be stopped and all database connections closed.

These commands support the SQLite server database. They do not back up client caches/outboxes or implement PostgreSQL backup and recovery. Deployment automation and release publication are separate work.

## Choose the database and storage location

Activate the project's Python 3.14 environment and run commands from the repository root. Always supply the actual database file explicitly. The development launcher normally uses `server/riskapp.db`; Compose uses `/data/riskapp.db` inside the API container. A relative SQLite URL is resolved against the server process's working directory, not against this tool's working directory.

Use a protected backup directory outside the checkout. Database snapshots contain password hashes, token hashes, accounts, and project data. On Unix, published files have mode `0600`; on Windows, restrict the directory's ACL to the operator and backup account. Store an additional encrypted copy outside the database host and its volume, and verify that copied file. A backup on the same PVC alone does not protect against loss of that PVC.

The running deployment's `SECRET_KEY` and `TOKEN_HASH_KEY` must be recoverable through a separate protected secret store. They are not embedded in a snapshot. Restoring the original keys preserves access-token validation and refresh/reset token validation. Recovery with different keys invalidates the corresponding tokens.

## Create and verify a snapshot

Git Bash or Linux, with the repository environment active:

```bash
mkdir -p -m 700 ../riskapp-backups
backup_file="../riskapp-backups/server-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
python scripts/server_database.py backup \
  --database server/riskapp.db --output "$backup_file"
python scripts/server_database.py verify --backup "$backup_file"
```

PowerShell, with the repository environment active:

```powershell
New-Item -ItemType Directory -Force ../riskapp-backups | Out-Null
$backupFile = "../riskapp-backups/server-$((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')).sqlite3"
python scripts/server_database.py backup --database server/riskapp.db --output $backupFile
python scripts/server_database.py verify --backup $backupFile
```

Success prints JSON containing `path`, `revision`, and `sha256`. A failed operation returns exit code 1 and prints its error to stderr. Record the successful JSON in the backup inventory and compare the SHA-256 after copying to another location. Check the command's exit status before retaining, copying, or expiring backups.

Verification checks SQLite integrity, foreign keys, required server tables, and the Alembic revision. Versioned snapshots must match the migration head packaged with the tool. For an older revision, recover with the matching application version first and follow the normal migration procedure; do not edit its revision to make verification pass.

Existing backup files are never overwritten. Publication uses an atomic hard link on the destination filesystem; ordinary NTFS and Linux filesystems support this. Unsupported/network filesystems can reject publication, leaving no completed output. All staging handles are closed before publication and cleanup, including on Windows. `--timeout 30` is the default SQLite busy timeout and snapshot-copy deadline; verification itself is not a total wall-clock deadline.

Do not copy just the live `.db` file or delete `-wal`, `-shm`, or `-journal` files to obtain a backup. SQLite's [online backup API](https://www.sqlite.org/backup.html) handles a consistent committed snapshot while the source remains in use.

### Existing development databases without a migration revision

`AUTO_CREATE_SCHEMA=1` can create a current development database without `alembic_version`. Such databases require explicit `--allow-unversioned` on **backup, verify, and restore**. For example:

```bash
python scripts/server_database.py backup \
  --database server/riskapp.db --output "$backup_file" --allow-unversioned
python scripts/server_database.py verify --backup "$backup_file" --allow-unversioned
```

Their JSON reports `revision: null`. The tool still checks integrity, foreign keys, server tables, and current sync columns. Those checks are not proof that every column, constraint, and index matches an Alembic migration. This flag is for known current development schemas, never an automatic baseline stamp or a bypass for a versioned database with the wrong revision. Production should use explicit migrations and the default strict verification.

## Rehearse recovery before replacing the live database

1. Verify the off-host copy using the intended application version.
2. Restore into a new file, rather than replacing the live database:

   ```bash
   python scripts/server_database.py restore \
     --backup "$backup_file" \
     --database ../riskapp-backups/rehearsal.sqlite3 --offline
   ```

3. Start an isolated API against that file with the recovered secrets, a separate port, and no real clients connected. In Git Bash/Linux, from the repository root:

   ```bash
   export DATABASE_URL="$(python -c 'from pathlib import Path; print("sqlite+pysqlite:///" + (Path.cwd().parent / "riskapp-backups/rehearsal.sqlite3").as_posix())')"
   export AUTO_CREATE_SCHEMA=0
   cd server
   python -m uvicorn riskapp_server.main.app:create_app --factory \
     --env-file ../.env --host 127.0.0.1 --port 8010
    ```

   Use a disposable shell: its exported database settings must not leak into the normal startup session. For an unversioned development rehearsal, add the flag to restore and keep the same application version.

4. Check `/health`, login, expected users/projects/members, and representative domain data. Test refresh-token continuity where appropriate. Stop the rehearsal API cleanly. Measure elapsed recovery time and record the snapshot's age so that the chosen backup frequency and recovery objectives have evidence.

The automated drill uses a migrated database and real API calls. It recovers authentication, membership, refresh tokens, Help Desk data, audit data, receipt replays, and sequence counters, then accepts and pulls a new sync change. Other tests cover live WAL writes, corruption, foreign-key failures, stale revisions, locked sources, publication races, and replacement failures.

```bash
python -m pytest tests/server/ops/test_sqlite_backup.py -q
```

## Replace the live database during a recovery window

Pause every client's automatic synchronization, stop every API worker/instance, and confirm all database connections have closed. Preserve a verified snapshot of the current database if it is readable before replacing it. The `--offline` flag acknowledges this operational prerequisite; it does not stop processes or detect every open reader.

```bash
python scripts/server_database.py restore \
  --backup "$backup_file" --database server/riskapp.db --offline --replace
python scripts/server_database.py verify --backup server/riskapp.db
```

Use `--allow-unversioned` on both commands only for the development case described above. Existing destinations require `--replace`; absent destinations do not. Restore validates a staged copy before atomic replacement. If validation or replacement fails, the original target is retained. A target or snapshot with SQLite sidecars is rejected: find and stop the remaining owner instead of deleting the sidecars. Do not restart workers while recovery is running.

Keep clients paused while you restart the API with the recovered keys and perform the smoke checks. Restoring an older server database rewinds entity versions, sync receipts, and project sequence counters. A client's saved sequence can then be ahead of the server, causing its incremental pull to return HTTP 400. Data acknowledged after the backup can also remain only in client caches, outside their pending outboxes. The current client has no automatic reconciliation for this server rollback.

Use the [older-snapshot recovery demo](OLDER_SNAPSHOT_RECOVERY.md): preserve the old client database, start a new cache against the restored server, and explicitly re-enter selected later work. Its three integration tests cover stale cursors, preserved conflict payloads, leftover cached entities, and successful manual reapplication without modifying the preserved cache. Resetting the cursor alone does not rebuild the client database. Do not use the destructive development reset as a recovery shortcut. Automated multi-device reconciliation remains outside this demo.

## Container invocation

The runtime image contains the same tool as a module. With a protected `/backups` mount, an online backup can run inside the API container:

```bash
python -m riskapp_server.ops.sqlite_backup backup \
  --database /data/riskapp.db --output /backups/server-20261006T120000Z.sqlite3
```

For restore, stop all API containers and run this module in a one-off maintenance container with the same data volume and matching application image. The module does not need authentication secrets merely to copy or verify the SQLite file. Do not run restore through an active API container.