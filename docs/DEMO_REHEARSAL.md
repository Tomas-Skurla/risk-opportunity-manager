# Windows demo rehearsal

This checks offline persistence, reconnecting, a two-client conflict and recovery after restoring an older server backup. Use the disposable server on port `8001` and the client caches below. The demo files live in `../riskapp-demo`, outside the repository; the normal server database and client cache are not used.

Run every block from the repository root in **PowerShell**. Paste each whole `& { ... }` block at once: it groups dependent commands so a failure stops that block. Each block defines its own paths; it does not depend on variables left in another terminal. `$ErrorActionPreference` handles PowerShell errors, and explicit exit-code checks handle Python failures. `>>` is PowerShell's normal continuation prompt, not part of the commands to paste.

## 1. Prepare

Complete [Windows installation](SETUP_GUIDE.md#windows-installation), including the private `.env`, and run [the project checks](SETUP_GUIDE.md#2-run-the-checks). Keep the same `.env` keys and bootstrap credentials throughout the rehearsal. Read the login email and password locally; keep them out of screenshots.

In a **control terminal**, create the demo directory. This refuses an existing directory. If you kept a previous rehearsal, move its completed folder aside or follow the cleanup below before starting another run.

```powershell
& {
    $ErrorActionPreference = "Stop"
    $repoPath = (Resolve-Path .).Path
    $python = Join-Path $repoPath ".venv\Scripts\python.exe"
    $demoPath = Join-Path (Split-Path $repoPath -Parent) "riskapp-demo"
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Complete Windows installation first."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $repoPath ".env") -PathType Leaf)) {
        throw "Create .env using the Windows installation instructions first."
    }
    New-Item -ItemType Directory -Path $demoPath | Out-Null
    Write-Host "Demo directory: $demoPath"
}
```

## 2. Start the server and client A

In a separate **server terminal**, use this block for every server start:

```powershell
& {
    $ErrorActionPreference = "Stop"
    $repoPath = (Resolve-Path .).Path
    $python = Join-Path $repoPath ".venv\Scripts\python.exe"
    $demoPath = Join-Path (Split-Path $repoPath -Parent) "riskapp-demo"
    if (-not (Test-Path -LiteralPath $demoPath -PathType Container)) {
        throw "Prepare the demo directory first."
    }
    $env:ENV = "development"
    $env:AUTO_CREATE_SCHEMA = "1"
    $env:ENFORCE_HTTPS = "0"
    $env:ALLOWED_HOSTS = "127.0.0.1,localhost"
    $env:DATABASE_URL = "sqlite+pysqlite:///" + ((Join-Path $demoPath "server.sqlite3").Replace("\", "/"))
    Push-Location (Join-Path $repoPath "server")
    try {
        & $python -m uvicorn riskapp_server.main.app:create_app --factory `
            --env-file (Join-Path $repoPath ".env") --host 127.0.0.1 --port 8001
    } finally {
        Pop-Location
    }
}
```

Wait for `Application startup complete`. In the control terminal, this should return `status: ok` and `db: ok`:

```powershell
Invoke-RestMethod "http://127.0.0.1:8001/health"
```

In a separate **client A terminal**, run the block below. Use the same block in another terminal for B, changing `$clientTag` to `"b"`. Later, use `"recovered"` for the recovery client. On restart, use the same tag as before.

```powershell
& {
    $ErrorActionPreference = "Stop"
    $clientTag = "a"
    $repoPath = (Resolve-Path .).Path
    $python = Join-Path $repoPath ".venv\Scripts\python.exe"
    $demoPath = Join-Path (Split-Path $repoPath -Parent) "riskapp-demo"
    if (-not (Test-Path -LiteralPath $demoPath -PathType Container)) {
        throw "Prepare the demo directory first."
    }
    $env:RISKAPP_URL = "http://127.0.0.1:8001"
    $env:RISKAPP_ALLOW_HTTP = "1"
    $env:RISKAPP_AUTO_SYNC_INTERVAL_SECONDS = "0"
    $env:RISKAPP_LOCAL_DB = Join-Path $demoPath ("client-" + $clientTag + ".sqlite3")
    Write-Host "Client database: $env:RISKAPP_LOCAL_DB"
    Push-Location (Join-Path $repoPath "client")
    try {
        & $python -m riskapp_client.app
    } finally {
        Pop-Location
    }
}
```

Automatic sync is off so you control when each client talks to the server. Log in with the bootstrap account at `http://127.0.0.1:8001`. Create project `Demo rehearsal` and risk `Baseline` with probability `2` and all four impact fields at `3`. Click **Save Risk**, then **Sync Now**. The saved risk should be `R-001`, score `6`, with queue, conflicts and errors all `0`.

## 3. Offline edit and restart

1. Stop the server with **Ctrl+C** and wait for its terminal prompt. Leave A open.
2. Select **R-001**. Rename it `Offline draft A`, set probability `4`, keep the impacts at `3`, and click **Save Risk**. Expect score `12` and a queued change. Do not click **Sync Now** yet.
3. Close A normally and wait for its terminal prompt. Restart it with the same `"a"` tag while the server stays stopped.
4. Enter the same credentials. After the connection fails, choose **Work Offline as … (will sync later)**. **Work Fully Local** uses a separate, anonymous mode.
5. Select the project and R-001. Confirm the title, probability `4` and queued change survived. **Sync Now** must be available.

`ONLINE` on a client that connected earlier means an authenticated session, not a live network check. A newly started account-associated offline session shows `OFFLINE`. Failed requests must preserve queued work; retry timing and automatic reconnect are also covered by the [manual test checklist](TEST_GUIDE.md#offline-work) and automated tests. If a previous attempt left work in `retry`, wait for its saved retry time before expecting it to be sent again.


## 4. Reconnect and resolve a real conflict

1. Restart the server and check `/health`. Leave A's queued change unsent.
2. Start B with tag `"b"`, log in and sync the project. It should still have R-001 `Baseline`, probability `2`.
3. In B, select R-001, rename it `Accepted by B`, set probability `3`, save and sync. Keep the impacts at `3`.
4. In A, click **Sync Now**. Expect a reconnect and **Conflicts (1)**: B's server version is newer than A's queued edit.
5. Open the Conflict Center. The local copy should be `Offline draft A` / `4`; the server copy should be `Accepted by B` / `3`.
6. Choose **Later**, close A and restart it with tag `"a"`. The unresolved conflict and both copies should still be available.
7. Choose **Merge fields…**, use **Mine** for the title and **Server** for probability. Leave other differing fields on **Server**. Click **Queue merge**, close the Conflict Center and **Sync Now**.
8. Sync B. Both clients should show R-001 `Offline draft A`, probability `3`, impact `3`, score `9`, and queue, conflicts and errors all `0`.

The same setup can demonstrate **Keep mine** or **Use server** with a fresh conflict; the recorded run below exercised the field merge.

## 5. Back up and restore the server

The six recovery checkpoints are below. Stop at any error and retain the demo folder.

### Checkpoint 1: create and verify the backup

In A, select **R-001**, rename it `At backup`, save and sync until the queue is empty. Keep the server running. In the control terminal:

```powershell
& {
    $ErrorActionPreference = "Stop"
    $repoPath = (Resolve-Path .).Path
    $python = Join-Path $repoPath ".venv\Scripts\python.exe"
    $demoPath = Join-Path (Split-Path $repoPath -Parent) "riskapp-demo"
    $serverDb = Join-Path $demoPath "server.sqlite3"
    $backupFile = Join-Path $demoPath "server-at-backup.sqlite3"
    & $python scripts/server_database.py backup --database $serverDb --output $backupFile --allow-unversioned
    if ($LASTEXITCODE -ne 0) { throw "Backup failed. Stop here." }
    & $python scripts/server_database.py verify --backup $backupFile --allow-unversioned
    if ($LASTEXITCODE -ne 0) { throw "Backup verification failed. Stop here." }
}
```

Both commands print JSON. `revision: null` is expected: this demo uses automatic schema creation, so it needs `--allow-unversioned`. The tool still checks integrity, foreign keys and the required schema. Backup files are never overwritten. Keep the reported SHA-256 for comparison with the restored file.

### Checkpoint 2: sync newer server data

In A, select **R-001**, rename it `Accepted after backup`, save and sync. Then create **R-002**, title `Exists only after backup`, probability `2`, with all impacts at `3`. Save and sync. Confirm both risks are present and queue, conflicts and errors are all `0`.

### Checkpoint 3: save offline work and preserve the cache

Stop the server and wait for its terminal prompt. In A, select **R-001**, rename it `Queued offline draft`, set probability `5`, keep all impacts at `3`, and **Save Risk** without syncing. Expect score `15` and a queued change. R-002 should remain `Exists only after backup`.

Close A and B normally and wait for both terminal prompts. Preserve A's cache in the control terminal:

```powershell
& {
    $ErrorActionPreference = "Stop"
    $repoPath = (Resolve-Path .).Path
    $demoPath = Join-Path (Split-Path $repoPath -Parent) "riskapp-demo"
    $clientDb = Join-Path $demoPath "client-a.sqlite3"
    $preservedClient = Join-Path $demoPath "preserved-client-a.sqlite3"
    $hashFile = Join-Path $demoPath "client-a.sha256"
    foreach ($suffix in "-wal", "-shm", "-journal") {
        if (Test-Path -LiteralPath ($clientDb + $suffix)) {
            throw "SQLite sidecar remains: $clientDb$suffix. Stop; do not delete it."
        }
    }
    if ((Test-Path -LiteralPath $preservedClient) -or (Test-Path -LiteralPath $hashFile)) {
        throw "A preservation copy or hash already exists. Stop; keep the existing evidence."
    }
    $originalHash = (Get-FileHash -LiteralPath $clientDb -Algorithm SHA256).Hash
    Copy-Item -LiteralPath $clientDb -Destination $preservedClient
    $preservedHash = (Get-FileHash -LiteralPath $preservedClient -Algorithm SHA256).Hash
    if ($originalHash -ne $preservedHash) { throw "The copied cache does not match. Stop here." }
    Set-Content -LiteralPath $hashFile -Value $originalHash -Encoding ascii
    Write-Host "Client cache preserved; hashes match."
}
```

The recorded hash makes the final check independent of PowerShell variables. If sidecars remain, retain them and find the remaining connection; do not copy only the main file or delete sidecars to make the check pass.

### Checkpoint 4: restore the older backup

Keep the API and both clients stopped. The following block checks that the preservation files exist and the recovery cache is unused, then replaces **only the demo server database**:


```powershell
& {
    $ErrorActionPreference = "Stop"
    $repoPath = (Resolve-Path .).Path
    $python = Join-Path $repoPath ".venv\Scripts\python.exe"
    $demoPath = Join-Path (Split-Path $repoPath -Parent) "riskapp-demo"
    $backupFile = Join-Path $demoPath "server-at-backup.sqlite3"
    $serverDb = Join-Path $demoPath "server.sqlite3"
    foreach ($name in "server-at-backup.sqlite3", "server.sqlite3", "preserved-client-a.sqlite3", "client-a.sha256") {
        if (-not (Test-Path -LiteralPath (Join-Path $demoPath $name) -PathType Leaf)) {
            throw "Required rehearsal file is missing: $name"
        }
    }
    foreach ($suffix in "", "-wal", "-shm", "-journal") {
        if (Test-Path -LiteralPath (Join-Path $demoPath ("client-recovered.sqlite3" + $suffix))) {
            throw "Recovery cache already exists. Use a fresh rehearsal directory."
        }
    }
    & $python scripts/server_database.py restore --backup $backupFile --database $serverDb --offline --replace --allow-unversioned
    if ($LASTEXITCODE -ne 0) { throw "Restore failed. Stop here." }
    & $python scripts/server_database.py verify --backup $serverDb --allow-unversioned
    if ($LASTEXITCODE -ne 0) { throw "Restored database verification failed. Stop here." }
    Write-Host "Restore and verification passed."
}
```

Both JSON outputs should have the backup's SHA-256. `--offline` acknowledges that every API process is stopped; it does not stop them. If sidecars prevent the restore, find the remaining owner instead of removing the files. Restart the API with the server block and check `/health`. Keep A and B closed from now on.

### Checkpoint 5: recover selected work through a fresh cache

Start the client block with tag `"recovered"`. Log in and sync `Demo rehearsal`. Before editing, check:

| Record | Expected restored state |
| --- | --- |
| R-001 | `At backup`, probability `3`, impact `3`, score `9` |
| R-002 | Absent: it was created after the backup |

Select the **existing R-001 row**, so the editor is editing that risk rather than creating a new one. Re-enter `Queued offline draft`, probability `5`, with all impacts at `3`. Save and sync. Expect one risk, score `15`, and queue, conflicts and errors all `0`.

This creates a new edit against the restored version. Keep old change IDs and payloads in the preserved cache; do not bulk-replay them. Re-create later records only deliberately, checking parent relationships for actions and assessments.

### Checkpoint 6: restart and confirm preservation

Close the recovered client, restart it with the same `"recovered"` tag and sync. Confirm R-001 still shows `Queued offline draft`, probability `5`, impact `3`, score `15`, with one risk and queue, conflicts and errors all `0`.

In the control terminal, check both caches against the hash recorded before restoration:

```powershell
& {
    $ErrorActionPreference = "Stop"
    $repoPath = (Resolve-Path .).Path
    $demoPath = Join-Path (Split-Path $repoPath -Parent) "riskapp-demo"
    $originalHash = (Get-Content -LiteralPath (Join-Path $demoPath "client-a.sha256") -Raw).Trim()
    foreach ($name in "client-a.sqlite3", "preserved-client-a.sqlite3") {
        $currentHash = (Get-FileHash -LiteralPath (Join-Path $demoPath $name) -Algorithm SHA256).Hash
        if ($currentHash -ne $originalHash) { throw "Cache changed: $name" }
        Write-Host "$name unchanged: True"
    }
}
```

Both lines must report `True`. Future launches against this restored server must use the recovered cache. Resetting an old cache's cursor alone leaves later cached records behind. The [backup guide](BACKUP_RESTORE.md#clients-after-restoring-an-older-backup) explains the limits: this is manual recovery, not automatic reconciliation after a server rollback.

The recovery limit to explain: the snapshot defines which server writes survive. Later work may remain only in a client's cache or outbox. This demo preserves that evidence and reapplies selected fields through a fresh cache, it does not provide automatic multi-client reconciliation after server rollback.

## Recorded Windows rehearsal: 14 October 2026

The manually observed run passed these checks:

| Check | Observed result |
| --- | --- |
| Offline save and restart | The edited title, probability and queued work survived reopening the same cache |
| Reconnect and conflict | A's stale edit conflicted with B's accepted edit; both copies remained available after restarting A |
| Field merge | Both clients converged on the selected title and probability, with no queued work or conflict |
| Backup and older-snapshot restore | Backup and verification succeeded; the restored database matched the backup's SHA-256 |
| Fresh-cache recovery | The earlier risk was present and the later risk absent; the selected edit was re-entered and synced |
| Recovery restart and preservation | The recovered edit survived restart; the original and copied cache hashes were unchanged |

The initial restore command failed at argument parsing because variables were unset in that terminal. The corrected command completed successfully before recovery continued. An earlier intermittent restart issue was **not reproduced in this Windows run**; its cause was not established, so this is not evidence that it was fixed. The run verified the procedure using a timestamped demo folder and hashes retained in the control terminal. The blocks above make future runs independent of those terminal variables. This result records the observed application behavior, not an execution of every revised command block.

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

## Cleanup

1. Close every demo client normally. Stop the demo API with **Ctrl+C** and wait for its terminal prompt.
2. Keep the demo folder if a check failed or you want the evidence. If you want to discard a completed run, the following deletes its databases, backup, preservation copy and recorded hash. Run it from the repository root:

   ```powershell
   & {
       $ErrorActionPreference = "Stop"
       $repoPath = (Resolve-Path .).Path
       $demoPath = Join-Path (Split-Path $repoPath -Parent) "riskapp-demo"
       Remove-Item -LiteralPath $demoPath -Recurse
   }
   ```

3. Close all rehearsal terminals. Their `$env:` settings are process-local; closing those sessions clears the demo URL, database paths and disabled automatic-sync setting. Start a fresh terminal for normal development.

Keep `.venv` and the private `.env` for normal local development. The cleanup removes only the named demo folder. For a run made with a different folder name, such as the timestamped 14 October run, remove that exact folder instead; do not use a wildcard.

For background-sync behavior and recovery limits, see [the client guide](../client/README_CLIENT.md) and [backup and restore](BACKUP_RESTORE.md#clients-after-restoring-an-older-backup).
