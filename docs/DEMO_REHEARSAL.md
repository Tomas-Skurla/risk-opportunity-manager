# Windows demo rehearsal

Allow about 30 minutes for the first run. This exercises offline persistence, manual reconnect, a two-client conflict, and recovery from earlier server data. Use disposable demo records and the same application version throughout.

The rehearsal has its own server database, port `8001`, and separate client caches. It uses your existing private `.env` for the signing keys and bootstrap account. Your normal `server/riskapp.db` and default client cache are not used. Keep the demo folder outside the repository and keep credentials out of screenshots.

## 1. Prepare an isolated session

Run the project checks first. From the repository root in Git Bash, with the Windows environment active:

```bash
source .venv/Scripts/activate
bash scripts/check_project.sh
```

The focused automated rehearsal can also be run on its own:

```bash
python -m pytest tests/client/gui/test_manual_reconnect.py \
  tests/client/gui/test_automatic_sync.py \
  tests/client/integration/test_snapshot_recovery.py \
  tests/server/ops/test_sqlite_backup.py -q
```

Use PowerShell for the following launch and recovery commands. They call the Windows Python executable directly, so activating the environment is unnecessary. Open each terminal at the repository root:

```powershell
Set-Location "<your checkout path here>"
```

In a **control terminal**, create a new folder for this run:

```powershell
$repoPath = (Resolve-Path .).Path
$python = Join-Path $repoPath ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Create the project environment first." }
if (-not (Test-Path (Join-Path $repoPath ".env"))) {
    throw "Use the setup guide to create your private .env first."
}
$demoPath = Join-Path (Split-Path $repoPath -Parent) (
    "riskapp-demo-" + (Get-Date -Format "yyyyMMdd-HHmmss")
)
New-Item -ItemType Directory -Path $demoPath -ErrorAction Stop | Out-Null
$serverDb = Join-Path $demoPath "server.sqlite3"
$demoPath
```

Copy the printed folder path into the server/client blocks below. Open `.env` locally and read `INITIAL_SUPERUSER_EMAIL` and `INITIAL_SUPERUSER_PASSWORD`. Both must be populated to bootstrap this new demo database. Keep the same keys and account settings for every restart; rerunning credential generation is not part of this rehearsal.

## 2. Start the server and client A

In a **server terminal**, from the repository root:

```powershell
$repoPath = (Resolve-Path .).Path
$python = Join-Path $repoPath ".venv\Scripts\python.exe"
$demoPath = "PASTE THE PRINTED DEMO FOLDER PATH HERE"
if (-not (Test-Path $demoPath -PathType Container)) { throw "Invalid demo folder." }
$env:ENV = "development"
$env:AUTO_CREATE_SCHEMA = "1"
$env:ENFORCE_HTTPS = "0"
$env:ALLOWED_HOSTS = "127.0.0.1,localhost"
$env:DATABASE_URL = "sqlite+pysqlite:///" + (
    (Join-Path $demoPath "server.sqlite3").Replace("\", "/")
)
Push-Location (Join-Path $repoPath "server")
try {
    & $python -m uvicorn riskapp_server.main.app:create_app --factory `
        --env-file (Join-Path $repoPath ".env") --host 127.0.0.1 --port 8001
} finally {
    Pop-Location
}
```

Wait for `Application startup complete`. In the control terminal:

```powershell
Invoke-RestMethod "http://127.0.0.1:8001/health"
```

In a **client A terminal**, from the repository root:

```powershell
$repoPath = (Resolve-Path .).Path
$python = Join-Path $repoPath ".venv\Scripts\python.exe"
$demoPath = "PASTE THE PRINTED DEMO FOLDER PATH HERE"
if (-not (Test-Path $demoPath -PathType Container)) { throw "Invalid demo folder." }
$clientTag = "a"
$env:RISKAPP_URL = "http://127.0.0.1:8001"
$env:RISKAPP_ALLOW_HTTP = "1"
$env:RISKAPP_AUTO_SYNC_INTERVAL_SECONDS = "0"
$env:RISKAPP_LOCAL_DB = Join-Path $demoPath ("client-" + $clientTag + ".sqlite3")
Push-Location (Join-Path $repoPath "client")
try {
    & $python -m riskapp_client.app
} finally {
    Pop-Location
}
```

Log in with the bootstrap account and check the login dialog's URL is `http://127.0.0.1:8001`. Create a project named `Demo rehearsal`. Create a risk with title `Baseline` and probability `2`. Set the Cost, Time, Scope, and Quality impact fields to `3`; the read-only overall impact should be `3`. Leave other editable fields at their defaults. Click **Save Risk**, then **Sync Now**. Wait until the job finishes and the status shows `queued: 0`, `conflicts: 0`, and `errors: 0`.

Automatic sync is deliberately disabled so you control when each client's changes reach the server. After a successful test, you can repeat the reconnect portion with `RISKAPP_AUTO_SYNC_INTERVAL_SECONDS = "60"` to demonstrate the ordinary automatic mode.

## 3. Offline edit, failed sync, and restart

1. Stop the server with **Ctrl+C** in its terminal and wait for the process to finish. Leave client A running.
2. Select `Baseline`. Change its title to `Offline draft A` and probability to `4`. Click **Save Risk**. Confirm the edited values are visible and queued work is present.
3. Click **Sync Now** while the server remains stopped. Expect a failure or retry message. Confirm the values and pending work remain; a failed request must not discard the edit.
4. Close client A normally and wait for its terminal prompt. Relaunch it using the same block and `client-a.sqlite3` path, while the server is still down.
5. Enter the same account credentials. After the connection fails, choose **Work Offline as <email> (will sync later)**.
6. Select the demo project. Confirm `Offline draft A`, probability `4`, and the pending edit survived the process restart. **Sync Now** must be enabled.

The `ONLINE` label on a previously connected client indicates an authenticated session, not a continuous network health check. The failed request and preserved queue are the checks while the API is stopped. A client launched through the account-associated offline option should show `OFFLINE` until it reconnects.

Keep A open with its unsynced edit for the conflict test. Do not choose the fully local/anonymous option, because that session has no account reconnect factory.

If the earlier failed request left `retrying` work, synchronization respects its saved retry time. Wait for that delay to elapse, then click **Sync Now** again; do not edit the outbox or treat an immediate zero-push attempt as data loss.

## 4. Reconnect and resolve a real conflict

1. Restart the server using the same server block, database path, and `.env`. Verify `/health` again. Leave A open without clicking **Sync Now** yet.
2. Open a **client B terminal** at the repository root. Run the client block above with `$clientTag = "b"`; use the same demo folder, URL, account, and disabled automatic sync. B must use `client-b.sqlite3`, never A's cache.
3. In B, select the demo project and click **Sync Now** before editing. Confirm the server still has `Baseline`, probability `2`.
4. In B, change that risk to title `Accepted by B`, probability `3`. Save and sync successfully. Keep impact unchanged. B has now advanced the server's record version while A still holds its earlier edit.
5. In A, click **Sync Now**. The worker should reconnect, and the status should become `ONLINE`. Expect a conflict/attention message and **Conflicts (1)**. This is expected version protection, not a failed rehearsal.
6. Open **Conflicts (1)** and select the risk. Verify the local copy contains `Offline draft A` / `4` and the server copy contains `Accepted by B` / `3`.
7. Click **Later**, close A, and reopen it with the same cache while the API is running. Open the conflict again: both copies and the unresolved conflict must still be available.
8. Choose **Merge fields...**. Select **Mine** for the title and **Server** for probability. Leave the remaining differing fields on **Server**, then click **Queue merge**. Close the Conflict Center and click **Sync Now**.
9. In B, click **Sync Now**. Both clients should now show `Offline draft A`, probability `3`, with no unresolved conflict or pending edit for that risk.

This proves local persistence, worker-thread reconnect, version conflict detection, conflict persistence across restart, and deliberate field selection. You can repeat the same conflict with a new edit to demonstrate **Keep mine** or **Use server** separately.

## 5. Back up and recover earlier server contents

Keep the server running for the backup. In A, set the first risk's title to `At backup`, save, and sync until it is acknowledged.

In the control terminal, whose `$python`, `$demoPath`, and `$serverDb` were set
in step 1, run:

```powershell
$backupFile = Join-Path $demoPath "server-at-backup.sqlite3"
& $python scripts/server_database.py backup --database $serverDb `
    --output $backupFile --allow-unversioned
if ($LASTEXITCODE -ne 0) { throw "Backup failed; stop the drill." }
& $python scripts/server_database.py verify --backup $backupFile --allow-unversioned
if ($LASTEXITCODE -ne 0) { throw "Backup verification failed; stop the drill." }
```

Record the successful verification JSON. The explicit `--allow-unversioned` flag is needed because this isolated development server uses `AUTO_CREATE_SCHEMA=1`. It does not bypass validation of a mismatched migration revision. A repeated rehearsal needs a new demo folder; backup files are not overwritten.

Now create a visible gap between the snapshot and the later client:

1. In A, change the first risk to `Accepted after backup`, save, and sync.
2. Create a second risk named `Exists only after backup`, save, and sync.
3. Stop the server. In A, change the first risk to `Queued offline draft`, probability `5`. Save without syncing. Write down these field values and confirm pending work is present.
4. Close **both A and B** normally and wait for their processes to exit.

Preserve A's closed cache in the control terminal:

```powershell
$clientDb = Join-Path $demoPath "client-a.sqlite3"
foreach ($suffix in @("-wal", "-shm", "-journal")) {
    if (Test-Path ($clientDb + $suffix)) {
        throw "SQLite sidecars remain. Find the open owner and retain the whole set."
    }
}
$preservedClient = Join-Path $demoPath "preserved-client-a.sqlite3"
if (Test-Path $preservedClient) { throw "Preservation copy already exists." }
Copy-Item -LiteralPath $clientDb -Destination $preservedClient -ErrorAction Stop
$preservedHash = (Get-FileHash -LiteralPath $preservedClient -Algorithm SHA256).Hash
$originalHash = (Get-FileHash -LiteralPath $clientDb -Algorithm SHA256).Hash
if ($originalHash -ne $preservedHash) { throw "Client preservation copy differs." }
```

If sidecars remain, retain them and resolve the remaining open connection; do not delete them to make the check pass. The server backup tool validates server schemas and is not a client-cache backup tool.

With the API and clients still stopped, restore the earlier **demo server**:

```powershell
& $python scripts/server_database.py restore --backup $backupFile `
    --database $serverDb --offline --replace --allow-unversioned
if ($LASTEXITCODE -ne 0) { throw "Restore failed; stop the drill." }
& $python scripts/server_database.py verify --backup $serverDb --allow-unversioned
if ($LASTEXITCODE -ne 0) { throw "Restored database verification failed." }
```

`--replace` replaces only the explicitly selected demo server file. `--offline` acknowledges that you have stopped every API process; it does not stop them for you. If the restore rejects database sidecars, find the owner instead of removing them. Restart the API with the same server block and keys, then check `/health`.

Keep old clients A and B closed. Their cursors, cached records, and versions describe newer server data. Restoring the server does not reconcile those caches.

Start a **recovery client terminal** at the repository root. Use the client launch block with `$clientTag = "recovered"`. Before launching, confirm the cache is new:

```powershell
$demoPath = "PASTE THE PRINTED DEMO FOLDER PATH HERE"
if (Test-Path (Join-Path $demoPath "client-recovered.sqlite3")) {
    throw "Use a fresh recovery cache for this drill."
}
```

1. Log in, select the project, and click **Sync Now**. The first risk should be `At backup`; `Exists only after backup` should be absent. The bootstrap account and project should still exist because they were in the snapshot.
2. Re-enter the selected later values: title `Queued offline draft`, probability `5`. Save and sync. This creates a new edit against the restored version.
3. Restart the recovery client with the same recovered cache and sync again. Confirm the recovered edit remains, with no duplicate record or conflict.
4. In the control terminal, confirm the old caches were preserved unchanged:

```powershell
if ((Get-FileHash -LiteralPath $clientDb -Algorithm SHA256).Hash -ne $originalHash) {
    throw "The original client cache changed."
}
if ((Get-FileHash -LiteralPath $preservedClient -Algorithm SHA256).Hash -ne $preservedHash) {
    throw "The preservation copy changed."
}
```

Future launches against this restored demo server must use the recovered cache. Do not reconnect A/B, reset their cursors, or bulk-replay their old outboxes as a shortcut. Re-create later records only when you explicitly choose to recover them; actions and assessments also need their parent relationships checked.

The recovery limit to explain: the snapshot defines which server writes survive. Later work may remain only in a client's cache or outbox. This demo preserves that evidence and reapplies selected fields through a fresh cache; it does not provide automatic multi-client reconciliation after server rollback.

## Record the rehearsal outcome

| Check | Pass condition |
| --- | --- |
| Offline save | Edited values stay visible and pending while the API is down. |
| Failed request | The pending edit survives a failed sync. |
| Offline restart | The same cache restores values and pending work; manual sync is available. |
| Reconnect | Manual sync adopts the authenticated session and leaves the UI usable. |
| Conflict | A stale edit is blocked with both copies retained, including after restart. |
| Merge | Both clients see the chosen title/probability; the queue and conflict clear. |
| Backup | The online snapshot and its verification succeed. |
| Restore | The fresh cache sees earlier server contents, without later leftover records. |
| Reapplication | A selected later edit syncs against the restored version. |
| Preservation | Original and preserved client hashes remain unchanged. |

For any failure, record the step, client cache path, exact clicks, expected versus actual result, and the relevant client/server exception text. Include a screenshot of the status or conflict copies when useful, with secrets removed. Keep the demo databases until the issue is understood. Fix the specific defect, add a regression test for its cause, rerun that case, then rerun the project checks before the next full rehearsal.

Close the demo clients and stop the demo API after the run. Close their dedicated terminals so the demo environment settings do not carry into normal launches. For background-sync behavior and recovery limits, also see [the client guide](../client/README_CLIENT.md), [backup/restore](BACKUP_RESTORE.md), and [older-snapshot recovery](OLDER_SNAPSHOT_RECOVERY.md).
