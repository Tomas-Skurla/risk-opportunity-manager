# Background worker/backend contract

`BackgroundJobBackend` defines the four operations used by desktop jobs: `list_projects`, `sync_project`, `create_snapshot`, and `top_history`. `BackendFactory` returns this protocol; `SyncCallbacks` describes the cancellation and progress keyword arguments. Definitions live in `client/riskapp_client/domain/background_job_contracts.py`.

`OfflineFirstBackend.create_background_backend` returns this job interface. Mypy checks that its concrete facade supplies the expected methods, callbacks, and result types. Each production worker creates and closes its own SQLite connection inside its worker thread. The GUI keeps its separate connection.

Alternate and test backends are supported at the UI boundary: signature inspection handles synchronization methods that omit the callbacks. The optional `list_sync_projects` and `export_authenticated_remote` hooks use runtime capability discovery and narrow casts at the typed job boundary, and owned-store cleanup is discovered at runtime as well. The contract covers only the job operations, not the remote API, the general UI backend interface, or the job payloads.

Results and payloads are JSON-shaped dictionaries with `Any` values; only the backend and factory references are typed.

Validate from the repository root with the project environment active:

```bash
bash scripts/typecheck.sh
python -m pytest tests/client/gui/test_background_jobs.py \
  tests/client/gui/test_automatic_sync.py \
  tests/client/gui/test_gui_behavior_coverage.py -q
```