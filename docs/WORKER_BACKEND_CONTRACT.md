# Background worker/backend contract

`BackgroundJobBackend` defines the operations used by desktop jobs: project listing, synchronization, snapshots, and history, plus authenticated-session export and resource cleanup. `BackendFactory` constructs this interface. Definitions live in `client/riskapp_client/domain/background_job_contracts.py`.

`OfflineFirstBackend.create_background_backend` creates a facade with its own SQLite connection inside the worker thread. The worker calls `close()` in that same thread when the job finishes or fails. The GUI keeps its separate connection. Main-window backends must supply this factory and `can_auto_sync()`; the window does not share its backend with a worker implicitly. Both methods are part of the client `Backend` protocol, so mypy checks the window's backend as well as the worker's.

Workers call these methods directly. `sync_project` accepts cancellation and progress callbacks. Automatic sync uses `list_sync_projects`, which reports remote failures instead of silently falling back to cached projects; manual post-promotion refresh uses `list_projects`, which retains offline fallback. `export_authenticated_remote` supplies a recovered session when requested. Mypy checks the production facade against this contract. Test backends implement the operations exercised by each test; deliberately partial fakes use narrow type-checker exceptions.

Results and payloads are JSON-shaped dictionaries with `Any` values; only the backend and factory references are typed. Cleanup errors are logged without replacing the job result or preventing the worker from finishing.

Validate from the repository root with the project environment active:

```bash
bash scripts/typecheck.sh
python -m pytest tests/client/gui/test_background_jobs.py \
  tests/client/gui/test_automatic_sync.py \
  tests/client/gui/test_gui_behavior_coverage.py -q
```
