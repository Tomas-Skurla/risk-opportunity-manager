# Manual test checklist

A walk through the desktop app's main features, roles, offline work and sync, on empty development databases. The API rules themselves (rate limits, request size, password policy, superadmin protection, RBAC, sync conflicts) are covered by the automated suite under `tests/server/api/`.

## Before you start

Follow the [setup guide](SETUP_GUIDE.md) through step 3. To start from empty databases, stop both applications and run the [reset](SETUP_GUIDE.md#5-reset-local-data), which **deletes all server and client data, including unsynced changes**. `bash scripts/check_project.sh` should end with `All checks passed.`, and `/health` should return `{"status":"ok","db":"ok"}`.

You need two accounts: the superadmin from `.env`, and a regular user you register below.

## Accounts and roles

1. Log in as the superadmin. The sidebar is empty. Click **New Project** and create `Test Project`.
2. Restart the client, click **Register new account…** and register a user against `http://127.0.0.1:8000`. The user is logged in and sees no projects.
3. As the superadmin, open `Test Project` → **Members** and add the user as `member`. The list shows both accounts.
4. As the user, open **Members**: the superadmin is not listed. The user can create and save a risk, but the delete controls, member management and **Take snapshot now** are disabled.
5. The user cannot delete the project; the superadmin can open **Delete Project** and its confirmation. Cancel for `Test Project`, which the remaining checks use. Exercise actual deletion on a separate disposable project.

## Records

As the superadmin, in `Test Project`:

| Tab | Do | Expect |
| --- | --- | --- |
| Risks | New risk with probability 4 and impacts cost 5, time 3, scope 2, quality 1. Save, then change probability to 2 | Score 20, then 10: probability × the highest impact. A duplicate code is rejected |
| Opportunities | New opportunity with probability 3 and impact 4 | Score 12 |
| Matrix | Switch between risks, opportunities and both | A 5×5 grid, probability by impact, with counts matching the records |
| Actions | New `mitigation` action for the risk | The action appears, showing the risk's title |
| Assessments | Select the risk, enter probability 2, impact 3 and notes | The assessment appears with the assessor's email |
| Help Desk | Create a ticket, set it to `in_progress` and try the status and priority filters. **Sync Now** and restart. Then delete it, **Sync Now** and restart | The status survives the restart, and the deleted ticket does not come back |
| Top history | **Take snapshot now**, change some scores, snapshot again. Needs the manager role or higher and a connection | Both snapshots appear in the history |
| Risks | **Export CSV** | The file contains the visible, filtered risks |

## Offline work

**Fully local.** Click **Work Fully Local** at login, create a risk, restart and choose **Work Fully Local** again: the risk is still there. A user logged in online does not see this project, and the local session does not see server projects.

**Offline as a user.** Log in once, close the client and stop the server. Start the client, enter the credentials and choose **Work Offline as … (will sync later)**. Projects show `(offline, will sync)`. Create a project `Offline Test` with a few risks, then start the server and leave the client open. Within about a minute, plus any retry delay shown, the project is published and the suffix disappears without a restart. **Sync Now** still syncs immediately.

To check the backoff, stop the server again, save a change and watch the status line. The window stays responsive, retries do not run continuously, and the client recovers once the server is back.

**Duplicate names.** Create a project `Test` online, then another `Test` while offline and let it sync. It becomes `Test (2)`, or the next free suffix.

## Conflicts and recovery

Use the [Windows demo rehearsal](DEMO_REHEARSAL.md) for the controlled two-client conflict and older-snapshot recovery. It assigns separate caches, disables automatic sync, checks that a conflict survives restart, merges selected fields and checks convergence on both clients. Use a fresh conflict to exercise **Keep mine** or **Use server** separately.

The recovery portion preserves the old cache, restores the server, opens a fresh cache and re-enters selected work. Resetting only an old cache's cursor is insufficient, [backup and restore](BACKUP_RESTORE.md#clients-after-restoring-an-older-backup) explains why.
