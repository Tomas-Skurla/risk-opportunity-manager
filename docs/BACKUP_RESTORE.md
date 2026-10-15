# Server database backup and restore

`scripts/server_database.py` backs up, verifies and restores the SQLite server database. Backups use SQLite's [online backup API](https://www.sqlite.org/backup.html), so they include committed WAL data and the API can keep running; a restore needs every API process stopped. The tool does not cover client caches or PostgreSQL.

## Before you start

- Activate the Python 3.14 environment and run from the repository root. Always name the database file explicitly: the development launcher uses `server/riskapp.db`, and Compose uses `/data/riskapp.db` inside the container. A relative SQLite URL resolves against the server's working directory, not the tool's.
- Keep backups in a protected directory outside the checkout: they contain password hashes, token hashes, accounts and project data. Files are written with mode `0600` on Unix; on Windows, restrict the folder's ACL. Keep an encrypted copy off the database host, because a copy on the same volume or PVC does not survive losing it, and verify that copy too.
- `SECRET_KEY` and `TOKEN_HASH_KEY` are not in the backup. Keep them in a separate secret store; restoring with different keys invalidates existing tokens.

## Back up and verify

In Bash, with the Python environment active:

```bash
(
  set -euo pipefail
  mkdir -p -m 700 ../riskapp-backups
  backup_file="../riskapp-backups/server-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
  python scripts/server_database.py backup --database server/riskapp.db --output "$backup_file"
  python scripts/server_database.py verify --backup "$backup_file"
)
```

On Windows, use PowerShell from the repository root:

```powershell
& {
    $ErrorActionPreference = "Stop"
    $repoPath = (Resolve-Path .).Path
    $python = Join-Path $repoPath ".venv\Scripts\python.exe"
    $backupDir = Join-Path (Split-Path $repoPath -Parent) "riskapp-backups"
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    $serverDb = Join-Path $repoPath "server\riskapp.db"
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $backupFile = Join-Path $backupDir "server-$stamp.sqlite3"
    & $python scripts/server_database.py backup --database $serverDb --output $backupFile
    if ($LASTEXITCODE -ne 0) { throw "Backup failed. Stop here." }
    & $python scripts/server_database.py verify --backup $backupFile
    if ($LASTEXITCODE -ne 0) { throw "Backup verification failed. Stop here." }
}
```

Paste the complete block for your shell at once. It stops after a failure rather than continuing to the dependent command. These commands use the normal development database path; change that explicit path if your server uses another file. For a database created without migrations, add `--allow-unversioned` to both calls as explained below. The [Windows rehearsal](DEMO_REHEARSAL.md) already includes that option for its disposable database.

Success prints JSON with `path`, `revision` and `sha256`; a failure exits with code 1 and prints the error to stderr. Record the JSON and compare the SHA-256 after copying the file elsewhere. Verification checks integrity, foreign keys, the required tables and the Alembic revision, which must match the migration head of this application version. For an older revision, recover with the matching application version and then migrate; never edit the revision to make verification pass.

Existing files are never overwritten. A finished backup is published with an atomic hard link, which ordinary NTFS and Linux filesystems support; some network filesystems refuse it, and then no output is left behind. Never copy the live `.db` file, or delete its `-wal`, `-shm` or `-journal` files, to get a backup.

**Databases without a migration revision.** `AUTO_CREATE_SCHEMA=1` creates development databases without `alembic_version`. For those, backup, verify and restore need `--allow-unversioned`, and the JSON reports `revision: null`. Integrity, foreign keys, tables and sync columns are still checked, but that does not prove the schema matches a migration. The flag never stamps a revision or accepts a wrong one. Production should use migrations and the default strict verification.

## Rehearse a restore

Restore into a new file first, rather than over the live database:

Choose the backup by its printed path; replace `PASTE-TIMESTAMP` below. Each restore block names its input again rather than relying on a variable from the backup terminal. The commands below use Bash; the [Windows rehearsal](DEMO_REHEARSAL.md#checkpoint-4-restore-the-older-backup) provides a complete PowerShell restore.

```bash
(
  set -euo pipefail
  backup_file="../riskapp-backups/server-PASTE-TIMESTAMP.sqlite3"
  python scripts/server_database.py restore --backup "$backup_file" \
    --database ../riskapp-backups/rehearsal.sqlite3 --offline
  python scripts/server_database.py verify --backup ../riskapp-backups/rehearsal.sqlite3
)
```

Only after restore and verification succeed, start an API against it in a throwaway shell, with the recovered keys, a separate port and no real clients:

```bash
(
  set -euo pipefail
  test -f ../riskapp-backups/rehearsal.sqlite3
  DATABASE_URL="$(python -c 'from pathlib import Path; print("sqlite+pysqlite:///" + (Path.cwd().parent / "riskapp-backups/rehearsal.sqlite3").as_posix())')"
  export DATABASE_URL
  export AUTO_CREATE_SCHEMA=0
  cd server
  python -m uvicorn riskapp_server.main.app:create_app --factory \
    --env-file ../.env --host 127.0.0.1 --port 8010
)
```

Check `/health`, logging in, the expected users, projects and members, and some project data, then stop the API. Note how long the recovery took and how old the backup was, so the backup schedule rests on evidence.

`python -m pytest tests/server/ops/test_sqlite_backup.py -q` runs the automated drill. It restores a migrated database and checks logins, memberships, refresh tokens, Help Desk and audit data, receipt replays and sequence counters through the real API, then accepts and pulls a new sync change. Other cases cover live WAL writes, corruption, foreign-key failures, stale revisions, locked sources and failed replacements.

## Replace the live database

Pause automatic sync in every client, stop every API process and confirm that all database connections are closed. If the current database is readable, back it up first.

```bash
(
  set -euo pipefail
  backup_file="../riskapp-backups/server-PASTE-TIMESTAMP.sqlite3"
  python scripts/server_database.py restore --backup "$backup_file" --database server/riskapp.db --offline --replace
  python scripts/server_database.py verify --backup server/riskapp.db
)
```

`--offline` confirms that the API is stopped; it does not stop anything itself. `--replace` is required when the target exists. The restore validates a staged copy before an atomic swap and keeps the original if anything fails. Files with SQLite sidecars are refused: find the process that still has the database open instead of deleting them. Keep clients paused until the restarted API passes the same checks as the rehearsal.

In a container, the tool runs as `python -m riskapp_server.ops.sqlite_backup`. A backup can run inside the API container with a protected `/backups` mount. A restore must run in a one-off maintenance container with the same data volume and image while all API containers are stopped, never through a running API container.

## Clients after restoring an older backup

A restore rewinds record versions, sync receipts and the per-project sequence counters, but clients keep what they had:

| Point in time | Server | Existing client |
| --- | --- | --- |
| Backup taken | Risk version 1, `At backup` | In sync |
| Later work synced | Version 2, plus a second risk | Has both, and a newer watermark |
| Further offline edit | Unchanged | `Queued offline draft` in the outbox |
| Backup restored | Version 1, second risk gone | Still has the later data, watermark and edit |

If the client's watermark is ahead of the restored server, its pull fails with HTTP 400 (`snapshot_sequence precedes since_sequence`), and its queued edit can become a version conflict. Neither means the queued work may be discarded. Data acknowledged after the backup may also exist only in a client's cache, outside its outbox. The client has no automatic reconciliation for this, so recover by hand:

1. Close every client and keep a copy of its database (by default `~/.riskapp/client.sqlite3`, on Windows `%USERPROFILE%\.riskapp\client.sqlite3`). Copy it only when no `-wal`, `-shm` or `-journal` file remains next to it.
2. Start a client with a new, unused cache and automatic sync off, for example `RISKAPP_LOCAL_DB="$HOME/.riskapp/client-recovered.sqlite3" RISKAPP_AUTO_SYNC_INTERVAL_SECONDS=0 bash scripts/run_client_dev.sh`, and sync. It receives exactly the restored data.
3. Re-enter the later changes you decide to keep; they become new edits against the restored versions. Re-create later records only deliberately, and check the parents of actions and assessments. Do not import old payloads or replay old change IDs.
4. Keep the old database until the recovery is verified, and keep using the new cache with this server.

Resetting the watermark alone is not enough: pulls merge rows rather than rebuild the cache, so records created after the backup would stay in the old cache. `tests/client/integration/test_snapshot_recovery.py` covers these cases, and the [demo rehearsal](DEMO_REHEARSAL.md#5-back-up-and-restore-the-server) walks through them.
