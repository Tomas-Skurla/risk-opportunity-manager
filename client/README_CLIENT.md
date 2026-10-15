# RiskApp Desktop Client

The PySide6 client keeps a local SQLite cache and an outbox, synchronizes in the background and offers **Sync Now** for an immediate run. The [setup guide](../docs/SETUP_GUIDE.md#3-start-the-server-and-the-client) covers starting it; [ARCHITECTURE.md](../docs/ARCHITECTURE.md) explains the synchronization design.

## Logging in and offline modes

The login dialog offers:

- **OK**: log in to the server with email and password.
- **Register new account…**: create a regular server account.
- **Work Fully Local (no account, no sync)**: work without an account; the data stays on this machine.
- **Cancel**: quit.

If the server is unreachable after **OK**, a **Server unavailable** dialog offers **Work Offline as `<email>` (will sync later)**, **Work Fully Local** or **Quit**.

| Mode | Account | Syncs | Sidebar label |
| --- | --- | --- | --- |
| Online | yes | yes | owner email, if known |
| Offline as a known user | the identity entered at login | automatically once the server is back | `(offline, will sync)` |
| Fully local | none | never | `(local only)` |

Online, every change is still written locally first and queued, so work continues if the server goes down mid-session. Automatic sync starts shortly after launch, syncs the visible projects periodically and sooner when there is queued work, and backs off after failures. When an offline project is synced and its name already exists on the server, a suffix is added, for example `Test Project (2)`.

Snapshot creation, snapshot history and member administration require a connection. While offline, Top history shows an inline reconnect message and skips the history request.

## Tabs

| Tab | Contents |
| --- | --- |
| Risks, Opportunities | Registers scored as probability × impact |
| Matrix | Probability × impact matrix |
| Top history | Snapshots of the top items over time |
| Actions | Mitigation, contingency and exploit actions |
| Assessments | Each user's own scoring of risks and opportunities |
| Members | Project members and roles |
| Help Desk | Support tickets per project; in server-backed projects they sync like other records |

## Roles

| Role | Scope | Can do |
| --- | --- | --- |
| superadmin | global | Admin rights in every project, plus deleting projects and the other operations under `/admin` |
| admin | per project | Everything a manager can, plus managing the project's members |
| manager | per project | Everything a member can, plus deleting risks, opportunities and actions, and taking snapshots |
| member | per project | Creating and editing risks, opportunities, actions, assessments and Help Desk tickets |
| viewer | per project | Read-only access |

The first superadmin is created by the server's [bootstrap settings](../server/README_SERVER.md#superadmin-bootstrap). To add a user to a project, log in as a superadmin or as the project's admin, open **Members**, enter the user's email and role, and click **Add/Update**. Only superadmins can delete a project: select it and click **Delete Project**, which permanently deletes it and its server data. The server enforces every permission; the client's role checks only decide which controls are enabled.


## Resolving sync conflicts

A change that collides with a newer edit on the server waits in the **Conflict Center**, which shows both versions:

- **Keep mine** sends your version again, based on the server's current version.
- **Use server** discards your change and applies the server's version.
- **Merge fields…** lists every field that differs, with both values. Choose **Mine** for at least one field, leave the others on **Server**, and click **Queue merge**.
- **Later** leaves it for now.

Fields that identify a record, link it to its parent or are calculated (automatic timestamps, version, scores) cannot be merged; editable dates such as `identified_at` can. For a deleted record, use **Keep mine** or **Use server**. If the saved server copy is out of date, synchronize again before merging.

## Editing the UI

The Qt Designer forms live in `client/riskapp_client/ui_v2/forms/`. After editing a form, regenerate only its `ui_*.py` with the pinned PySide6, for example:

```bash
pyside6-uic client/riskapp_client/ui_v2/forms/conflict_center_dialog.ui -o client/riskapp_client/ui_v2/ui/ui_conflict_center_dialog.py
```

Button behaviour and dynamic merge rows live in the `components/` files, so regenerating a form cannot overwrite them.
