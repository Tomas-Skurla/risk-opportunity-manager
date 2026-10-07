# RiskApp Desktop Client

PySide6 desktop client for RiskApp.

## Overview

- Local SQLite cache with an outbox.
- Automatic background sync with manual **Sync Now** fallback.
- Commit-safe incremental pulls using a persisted server sequence.
- Sidebar views for Risks, Opportunities, Matrix, Top history, Actions, Assessments, Members, and Help Desk.
- Online login, account registration, offline-as-user mode, and fully local anonymous mode.
- Qt/PySide runtime diagnostics through `scripts/diagnose_qt_runtime.sh`.

## Running the client

The [setup guide](../docs/SETUP_GUIDE.md#7-start-the-client) covers installing and starting the client, with or without the launcher script.

## Logging in

The login dialog has four options:

- **OK** — login to the server with email and password.
- **Register new account…** — create a regular server account.
- **Work Fully Local (no account, no sync)** — work without an account. Data stays on this machine and does not sync.
- **Cancel** — quit the application.

If the server is unreachable after clicking **OK**, a **Server Unavailable** dialog appears with:

- **Work Offline as `<your email here>` (will sync later)** — offline mode associated with that identity. The client retries in the background after the server becomes available; **Sync Now** remains available for an immediate attempt.
- **Work Fully Local (no account, no sync)** — anonymous local mode; data never syncs.
- **Quit** — exit.

## Registering an account

### From the client

1. Launch the client.
2. Click **Register new account…**.
3. Fill in:
   - Server URL: `http://127.0.0.1:8000`
   - Email: `<your email here>`
   - Password: `<your password here>`
4. Click **OK**.

### Through the API

See [regular registration](../server/README_SERVER.md#regular-registration) in the server guide.

Registration creates a regular user, not a global superadmin.

## Offline modes

| Mode | Account? | Server required? | Sync later? | Sidebar label |
| --- | ---: | ---: | ---: | --- |
| Online | yes | yes at login | yes | owner email if known |
| Offline as known user | known identity | no | yes, automatically after connectivity returns | `(offline, will sync)` |
| Fully local anonymous | no | no | no | `(local only)` |

### Work Fully Local

- No account or server required.
- Data is stored in `~/.riskapp/client.sqlite3`.
- Projects show `(local only)`.
- Data never syncs to the server.

### Work Offline as `<your email here>`

- Intended for a known identity when the server is unavailable.
- Data is stored locally with that identity.
- Projects show `(offline, will sync)`.
- The client reconnects and syncs automatically after the server becomes available. **Sync Now** forces an immediate attempt.
- If a project name already exists on the server, a numeric suffix is added, for example `Test Project (2)`.

### Online with offline fallback

- Normal online login.
- Changes are written locally and queued in the outbox.
- If the server goes down mid-session, local work can continue.
- Background sync recovers automatically with bounded backoff; **Sync Now** remains available.

Automatic sync starts shortly after launch, runs on a worker-owned SQLite connection, and periodically pulls every visible project. Local queued work requests an earlier run. Transient connectivity failures use bounded exponential backoff and persisted outbox retry timestamps. **Sync Now** remains available for an immediate, user-visible run.

## Sidebar project labels

| Label | Meaning |
| --- | --- |
| `Project Name  (<owner email here>)` | Server project with owner email |
| `Project Name  (offline, will sync)` | Local project associated with an identity; can sync later |
| `Project Name  (local only)` | Anonymous local project; never syncs |
| `Project Name` | Server project with owner unknown |

## Tabs

| Tab | Description |
| --- | --- |
| Risks | Risk register with qualitative probability × impact scoring |
| Opportunities | Opportunity register with qualitative probability × impact scoring |
| Matrix | Probability × impact matrix view |
| Top history | Snapshot tracking of top-N items over time |
| Actions | Mitigation, contingency, and exploit actions |
| Assessments | Per-user scoring of risks and opportunities |
| Members | Project member and role management |
| Help Desk | Per-project support tickets with offline-first sync for server-backed projects |

## Roles

| Role | Scope | Can do |
| --- | --- | --- |
| **superadmin** | global | Admin rights in every project, plus deleting projects and the other operations under `/admin` |
| **admin** | per project | Everything a manager can, plus managing the project's members |
| **manager** | per project | Everything a member can, plus deleting risks, opportunities and actions |
| **member** | per project | Create and edit risks, opportunities, actions, assessments and Help Desk tickets, and take snapshots |
| **viewer** | per project | Read-only access |

The first superadmin is created when the server starts; see [the server guide](../server/README_SERVER.md#superadmin-bootstrap). Project roles are assigned in the **Members** tab.

## Adding a user to a project

1. Log in as a superadmin or as an admin of the project.
2. Create or select a project.
3. Open the **Members** tab.
4. Enter the user's email address and choose a role.
5. Click **Add/Update**.

The user can now log in and see that project.

## Deleting a project

Only global superadmins can delete projects.

1. Log in as a superadmin.
2. Select the project in the sidebar.
3. Click **Delete Project**.
4. Confirm the warning dialog.

This permanently deletes the project and its server-side data.

## Resolving sync conflicts

When a change you made collides with a newer edit on the server, it waits in the **Conflict Center**, which shows both versions:

- **Keep mine** sends your version again, based on the server's current version.
- **Use server** discards your change and applies the server's version.
- **Merge fields…** lists every field that differs, with both values. Choose **Mine** for at least one field, leave the others on **Server**, and select **Queue merge**. **Cancel** leaves the conflict unresolved.
- **Later** leaves it for now.

Fields that identify a record, link it to its parent, or are calculated (automatic timestamps, version, scores) cannot be chosen in a merge; editable dates such as `identified_at` can. For a deleted record, use **Keep mine** or **Use server**. If the saved server copy is out of date, synchronize again before merging. For how this works underneath, see [ARCHITECTURE.md](../docs/ARCHITECTURE.md#33-resolving-a-conflict).

## Configuration

Every setting is listed in the [configuration reference](../docs/SETUP_GUIDE.md#10-environment-variables-reference).

## Qt/PySide diagnostics

If the client fails to start with missing native libraries, see [step 4 of the setup guide](../docs/SETUP_GUIDE.md#4-diagnose-qtpyside-runtime-libraries).

## Editing the UI

The editable Qt Designer sources live in `client/riskapp_client/ui_v2/forms/`. After editing a form, regenerate only its matching `ui_*.py` from the repository root, using the pinned PySide6 environment. For example:

```bash
pyside6-uic client/riskapp_client/ui_v2/forms/conflict_center_dialog.ui -o client/riskapp_client/ui_v2/ui/ui_conflict_center_dialog.py
```

For a different form, substitute its name in both paths. Keep button behavior and dynamic merge rows in the `components/` files, so regenerating a form cannot overwrite them. The conflict forms use lowercase names in their Designer `<class>` tags; the components alias the resulting generated class names on import.

## Notes

- Server-side authorization is authoritative.
- Client-side role checks shape UI behavior only.
- Help Desk tickets are stored locally and, for server-backed projects, participate in offline-first sync.
- In **Work Fully Local** mode, Help Desk tickets remain local like the rest of the anonymous local project data.
