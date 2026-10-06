# Background worker/backend contract

`BackgroundJobBackend` defines the four operations used by desktop jobs: `list_projects`, `sync_project`, `create_snapshot`, and `top_history`. `BackendFactory` returns this protocol instead of `Any`; `SyncCallbacks` describes the cancellation and progress keyword arguments. Definitions live in `client/riskapp_client/domain/background_job_contracts.py`.

`OfflineFirstBackend.create_background_backend` returns this job interface. Mypy checks that its concrete facade supplies the expected methods, callbacks, and result types. Each production worker still creates and closes its own SQLite connection inside its worker thread. The GUI keeps its separate connection.

Existing alternate/test backends remain supported at the UI boundary. Signature inspection is retained for their synchronization methods that omit callbacks. The optional `list_sync_projects` and `export_authenticated_remote` hooks use runtime capability discovery and narrow casts at the typed job boundary. Owned-store cleanup retains its existing runtime discovery. This change does not replace the remote API, rewrite the general UI backend interface, or change job payloads.

Results and payload fields retain their existing JSON-shaped dictionaries. Their `Any` values are separate from the now-typed backend and factory references; a full result-schema redesign would be a larger change.

Validate from the repository root with the project environment active:

```bash
bash scripts/typecheck.sh
python -m pytest tests/client/gui/test_background_jobs.py \
  tests/client/gui/test_automatic_sync.py \
  tests/client/gui/test_gui_behavior_coverage.py -q
```