# RiskApp — Test Guide

This guide verifies a clean local setup, automated checks, GUI startup, core functionality, RBAC, offline work, and sync.

**Prerequisite:** complete [`SETUP_GUIDE.md`](SETUP_GUIDE.md), or run the commands below from the repository root.

---

## 1. Clean automated setup

```bash
bash scripts/setup_os_prereqs.sh --desktop
bash scripts/setup_python_env.sh
bash scripts/diagnose_qt_runtime.sh
bash scripts/check_project.sh
```

If OS prerequisites are already installed:

```bash
bash scripts/bootstrap_dev.sh --skip-os-prereqs
```

Expected:

```text
All checks passed.
```

---

## 2. Clean runtime start

Terminal 1:

```bash
RESET_SERVER_DB=1 bash scripts/run_server_dev.sh
```

Terminal 2:

```bash
RESET_CLIENT_DB=1 bash scripts/run_client_dev.sh
```

---

## 3. Health check

```bash
curl -s -o /tmp/riskapp-health.json -w "HTTP %{http_code}\n" http://127.0.0.1:8000/health
cat /tmp/riskapp-health.json
```

Verify:

```text
HTTP 200
{"status":"ok","db":"ok"}
```

---

## 4. Superadmin login and project creation

1. Login dialog → `admin@example.com` / `SuperHeslo123!` → **OK**.
2. Verify the app enters online mode.
3. Verify the sidebar is empty on a clean database.
4. Click **New Project** → name `Test Project` → **OK**.
5. Verify the project appears in the sidebar.

---

## 5. Register a new user

1. Close and restart the client.
2. Click **Register new account…**.
3. Fill in:
   - Server URL: `http://127.0.0.1:8000`
   - Email: `user@example.com`
   - Password: `UserHeslo123!`
4. Confirm.
5. Verify registration succeeds and the user logs in.
6. Verify the sidebar is empty because the user is not yet a project member.

---

## 6. Add user to project

1. Log in as `admin@example.com`.
2. Select `Test Project` → **Members** tab.
3. Enter `user@example.com`, role `member` → **Add/Update**.
4. Verify the table shows `user@example.com` with role `member`.
5. Verify the superadmin can see both themselves and the regular user.

---

## 7. Superadmin invisibility for regular users

1. Log in as `user@example.com`.
2. Select `Test Project` → **Members** tab.
3. Verify the regular user does not see the superadmin in the members list.
4. Verify the user has the expected project role.

---

## 8. Superadmin protection through API

A regular user must not be able to change a superadmin's role.

```bash
BASE=http://127.0.0.1:8000

LOGIN=$(curl -s -X POST "$BASE/login" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'username=user@example.com&password=UserHeslo123%21')
TOKEN=$(echo "$LOGIN" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

PID=$(curl -s "$BASE/projects" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; ps=[p for p in json.load(sys.stdin) if 'Test Project' in p['name']]; print(ps[0]['id'])")

curl -s -o /tmp/riskapp-superadmin-protection.json -w "HTTP %{http_code}\n" \
  -X POST "$BASE/projects/$PID/members" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"user_email":"admin@example.com","role":"viewer"}'
cat /tmp/riskapp-superadmin-protection.json
```

Verify HTTP `403` and an error explaining that only a superadmin can change another superadmin's role.

---

## 9. RBAC: member cannot delete

1. Log in as `user@example.com`.
2. Select `Test Project` → **Risks** tab → **New**.
3. Fill in a risk and save.
4. Verify the risk appears.
5. Verify member-level UI does not expose manager/admin-only destructive controls.

---

## 10. Risks

1. Log in as `admin@example.com`.
2. `Test Project` → **Risks** tab → **New**.
3. Fill in:
   - Title: `Server outage`
   - Probability: `4`
   - Impact cost: `5`
   - Impact time: `3`
   - Impact scope: `2`
   - Impact quality: `1`
   - Description: `Main server outage`
   - Category: `Technical`
   - Status: `active`
4. Save.
5. Verify score is `20`: probability `4` × effective impact `5`.
6. Change probability to `2` and save.
7. Verify score is `10`.

The code field is unique per project; duplicates should trigger an error.

---

## 11. Opportunities

1. Open **Opportunities** → **New**.
2. Title: `New market`, Probability: `3`, Impact: `4` → Save.
3. Verify the button says **Save Opportunity**.
4. Verify score is `12`.

---

## 12. Matrix

1. Open **Matrix**.
2. Verify a 5×5 table appears.
3. Verify rows are probability `1..5` and columns are impact `1..5`.
4. Verify each cell count matches risks/opportunities with that probability × impact combination.
5. Switch between risks, opportunities, and both.

---

## 13. Actions

1. Open **Actions** → **New**.
2. Target: risk `Server outage`.
3. Kind: `mitigation`.
4. Title: `Backup server`.
5. Save.
6. Verify the action appears in the table.

---

## 14. Assessments

1. Open **Risks** → select `Server outage`.
2. Open **Assessments**.
3. Enter Probability `2`, Impact `3`, and notes.
4. Save.
5. Verify the assessment appears and the assessor column shows an email address when available.

---

## 15. Help Desk

1. Open **Help Desk** → **New ticket**.
2. Title: `Export does not work`, Category: `bug`, Priority: `high` → Save.
3. Verify the ticket appears.
4. Select it, change status to `in_progress`, and save.
5. Test status and priority filters.
6. Run **Sync Now** on the current server-backed project.
7. Restart the client or pull the project again.
8. Verify the ticket persists with the updated status.
9. Delete the ticket and confirm it disappears.
10. Run **Sync Now** again.
11. Verify the deleted ticket does not reappear after refresh/restart.

In server-backed projects, Help Desk tickets participate in sync. In **Work Fully Local** mode, they remain local to the anonymous project.

---

## 16. Work Fully Local

1. Start the client, then click **Work Fully Local** in the login dialog.
2. Verify the sidebar contains a local-only project or allows you to create one.
3. Create a risk and save it.
4. Close the client.
5. Start it again and choose **Work Fully Local**.
6. Verify the risk still exists.
7. Log in online as `admin@example.com`.
8. Verify the anonymous local project is not visible.

---

## 17. Work Offline as user, then sync later

1. Start the client and log in as `admin@example.com` while the server is running.
2. Close the client.
3. Stop the server with `Ctrl+C`.
4. Start the client again.
5. Enter `admin@example.com` and password → **OK**.
6. In the server-unavailable dialog, click **Work Offline as admin@example.com (will sync later)**.
7. Verify the sidebar shows projects with `(offline, will sync)` where applicable.
8. Create project `Offline Test` and add risks.
9. Start the server again.
10. Close the client, start it, and log in online.
11. Select `Offline Test` and click **Sync Now**.
12. Verify the project is promoted and the offline suffix disappears.

---

## 18. Project isolation

1. Log in online and create project `Online A`.
2. Start a local-only session and create project `Local B`.
3. Verify the local user does not see `Online A`.
4. Verify the online user does not see `Local B`.

---

## 19. Duplicate project name

1. Log in online and create `Test`.
2. Create another project named `Test`.
3. Verify the client/server flow avoids collision, for example with `Test (2)`.
4. Create an offline project named `Test`.
5. Promote it while the server already has `Test`.
6. Verify it becomes `Test (2)` or the next available suffix.

---

## 20. Sync and conflict resolution

### Online sync

1. Create risks.
2. Click **Sync Now**.
3. Verify there are no pending changes.

### Conflict test with two clients

```bash
# Terminal 2: Client A
bash scripts/run_client_dev.sh

# Terminal 3: Client B
bash scripts/run_client_dev.sh
```

1. Client A: create risk `Conflict Test` → save → **Sync Now**.
2. Client B: **Sync Now** → risk appears.
3. Client B: change title to `Changed by B` → save → **Sync Now**.
4. Client A, without syncing first: change title to `Changed by A` → save → **Sync Now**.
5. Expected result is either automatic retry success or a blocked-change warning if retry cannot resolve the conflict.

### Conflict test via curl

```bash
BASE=http://127.0.0.1:8000

LOGIN=$(curl -s -X POST "$BASE/login" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'username=admin@example.com&password=SuperHeslo123%21')
TOKEN=$(echo "$LOGIN" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

PID=$(curl -s "$BASE/projects" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")

RISK=$(curl -s -X POST "$BASE/projects/$PID/risks" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Conflict Test","probability":3,"impact":4}')
RID=$(echo "$RISK" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Risk: $RID, version 1"

curl -s -X PATCH "$BASE/projects/$PID/risks/$RID" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Changed by B","probability":5}' > /dev/null
echo "Client B -> version 2"

CID=$(python3 -c "import uuid; print(uuid.uuid4())")
echo "Client A push with stale base_version=1"
curl -s -X POST "$BASE/projects/$PID/sync/push" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"project_id\":\"$PID\",\"changes\":[{\"change_id\":\"$CID\",\"entity\":\"risk\",\"op\":\"upsert\",\"base_version\":1,\"record\":{\"id\":\"$RID\",\"title\":\"Changed by A\",\"probability\":1,\"impact\":1}}]}" \
  | python3 -m json.tool

CID2=$(python3 -c "import uuid; print(uuid.uuid4())")
echo "Client A retry with base_version=2"
curl -s -X POST "$BASE/projects/$PID/sync/push" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"project_id\":\"$PID\",\"changes\":[{\"change_id\":\"$CID2\",\"entity\":\"risk\",\"op\":\"upsert\",\"base_version\":2,\"record\":{\"id\":\"$RID\",\"title\":\"Changed by A (resolved)\",\"probability\":1,\"impact\":1}}]}" \
  | python3 -m json.tool
```

---

## 21. Delete project

1. Log in as superadmin.
2. Select a project → **Delete Project** → confirm.
3. Verify the project disappears.
4. Log in as a regular user and try to delete if the UI exposes the control.
5. Verify deletion is denied.

---

## 22. Rate limiting

```bash
BASE=http://127.0.0.1:8000

for i in $(seq 1 6); do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$BASE/register" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"test${i}@example.com\",\"password\":\"TestHeslo1234!\"}")
  echo "Register attempt $i: HTTP $CODE"
done

for i in $(seq 1 11); do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$BASE/login" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    -d 'username=fake@example.com&password=WrongPassword1')
  echo "Login attempt $i: HTTP $CODE"
done
```

Expect a `429` after the configured limit is exceeded.

---

## 23. Request body size limit

```bash
python3 -c "print('{\"email\":\"x@x.com\",\"password\":\"' + 'A'*3000000 + '\"}')" > /tmp/riskapp-big.json
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  -X POST http://127.0.0.1:8000/register \
  -H 'Content-Type: application/json' \
  -H "Content-Length: $(wc -c < /tmp/riskapp-big.json)" \
  -d @/tmp/riskapp-big.json
rm /tmp/riskapp-big.json
```

Expected: `HTTP 413`.

---

## 24. Password policy

```bash
BASE=http://127.0.0.1:8000

curl -s -o /tmp/riskapp-pw-short.json -w "HTTP %{http_code}\n" \
  -X POST "$BASE/register" \
  -H 'Content-Type: application/json' \
  -d '{"email":"w1@example.com","password":"short"}'
cat /tmp/riskapp-pw-short.json

curl -s -o /tmp/riskapp-pw-upper.json -w "HTTP %{http_code}\n" \
  -X POST "$BASE/register" \
  -H 'Content-Type: application/json' \
  -d '{"email":"w2@example.com","password":"nouppercase123!"}'
cat /tmp/riskapp-pw-upper.json

curl -s -o /tmp/riskapp-pw-valid.json -w "HTTP %{http_code}\n" \
  -X POST "$BASE/register" \
  -H 'Content-Type: application/json' \
  -d '{"email":"valid@example.com","password":"ValidHeslo123!"}'
cat /tmp/riskapp-pw-valid.json
```

Expected invalid-password cases return HTTP `400`; valid registration returns HTTP `201` unless the email already exists.

---

## 25. Top history / snapshots

1. Log in as admin or manager-level user.
2. Create several risks with different scores.
3. Open **Top history** → **Snapshot now**.
4. Verify a snapshot appears.
5. Change scores and create another snapshot.
6. Verify trend/history changes.

Snapshots require a server-backed/synced project.

---

## 26. CSV export

1. Open **Risks**.
2. Click **Export CSV**.
3. Verify a CSV file is created and includes the visible filtered risk list.

If your OS lacks a spreadsheet viewer, install LibreOffice Calc through OS packages or run:

```bash
bash scripts/setup_os_prereqs.sh --all
```

---

## 27. Automated tests and lint

```bash
bash scripts/check_project.sh
```

Or directly:

```bash
bash scripts/test.sh
bash scripts/lint.sh
python -m pip check
```

Coverage includes registration, login, password policy, rate limiting, RBAC, refresh tokens, sync push/pull, conflict detection, assessments, search escaping, password reset, SQLite migrations, outbox queue, and Help Desk sync/version behavior.
