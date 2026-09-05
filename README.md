# Offline Risk & Opportunity Manager

RiskApp is an offline-first risk and opportunity manager: a FastAPI/SQLAlchemy API and a PySide6 desktop client with a local SQLite cache, persistent synchronization outbox, version-based conflict detection, project RBAC, audit receipts, and hashed rotating refresh tokens.

## What this repository demonstrates

- layered desktop architecture with domain services behind UI-independent adapters;
- offline operation with persistent queued writes and bidirectional synchronization using server receipt deduplication plus incremental cursor pulls;
- a Qt Designer-backed Conflict Center that preserves unresolved writes and lets users explicitly keep the local copy, use the saved server copy, or decide later;
- authorization enforced consistently across REST and sync paths;
- bounded request/response handling, literal search escaping, and safe CSV export;
- isolated API and client-core tests plus Ruff, compile, and dependency checks;
- reproducible runtime lock files and an automated CI gate.

## Quick start

See [ARCHITECTURE.md](ARCHITECTURE.md) for boundaries, invariants, security choices, and explicit production trade-offs.

## Run the review checks

The suite runs Qt offscreen, so it does not need a display server but still requires the locked PySide6 runtime:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-test.txt
bash scripts/check_project.sh
```

The check script validates a fresh Alembic migration, runs tests with a 90% combined coverage gate plus independent 92% line and 80% branch ratchets, Ruff, byte-compilation, and `pip check`. CI runs the same command on every push and pull request. Black remains available through
`bash scripts/format.sh`; formatting-only normalization is intentionally separate.

## Run the application

For the complete desktop environment:

```bash
bash scripts/setup_os_prereqs.sh --desktop
bash scripts/setup_python_env.sh
bash scripts/diagnose_qt_runtime.sh
bash scripts/check_project.sh
```

Start the API:

```bash
RESET_SERVER_DB=1 bash scripts/run_server_dev.sh
```

Start the client in another terminal:

```bash
RESET_CLIENT_DB=1 bash scripts/run_client_dev.sh
```

The development launcher binds to localhost and bootstraps `admin@example.com` / `SuperHeslo123!`. These are local demo credentials only; deployed environments must provide their own secret and account settings. Interactive API documentation is available at `http://127.0.0.1:8000/docs`; health status is at `/health`.

## Run the development API with Docker

The container workflow packages only the FastAPI development server. The PySide6 desktop client continues to run natively so it can use the host desktop, local cache, and normal platform integration.

Start the API with its demo account and a persistent SQLite volume:

```bash
docker compose up --build
```

Verify it from another terminal:

```bash
curl http://127.0.0.1:8000/health
```

Then launch the native client with the existing script. Its development default already points to `http://127.0.0.1:8000`. To use another host port, set both the Compose mapping and the client URL:

```bash
RISKAPP_HOST_PORT=8080 docker compose up --build
RISKAPP_URL=http://127.0.0.1:8080 bash scripts/run_client_dev.sh
```

Stop the server while retaining its demo data with `docker compose down`. Remove the named SQLite volume and start from an empty server database with:

```bash
docker compose down --volumes
```

The separate test target installs the locked server and desktop dependencies, adds the Qt offscreen libraries, and runs the same migration, test, lint, compilation, and dependency checks as CI:

```bash
docker build --target test -t riskapp:test .
```

This is a local development/demo configuration. It deliberately preserves the repository's existing insecure demo secret and bootstrap credentials and is not a production deployment recipe.

## Repository map

```text
client/       PySide6 application, domain services, local store, HTTP adapter
server/       FastAPI routers, auth/RBAC, persistence, sync, operations
tests/        Canonical headless client-core and API regression suite
scripts/      Setup, quality, run, reset, and dependency-lock workflows
```

Detailed setup and manual acceptance flows remain in [SETUP_GUIDE.md](SETUP_GUIDE.md) and [TEST_GUIDE.md](TEST_GUIDE.md). Development commands are summarized in
[README_QA.md](README_QA.md).
