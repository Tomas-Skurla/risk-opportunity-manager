# Offline Risk & Opportunity Manager

[![CI](https://github.com/Tomas-Skurla/risk-opportunity-manager/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Tomas-Skurla/risk-opportunity-manager/actions/workflows/ci.yml)
[![Coverage gate](https://img.shields.io/badge/coverage%20gate-90%25%20combined-brightgreen)](docs/SETUP_GUIDE.md#5-run-automated-checks)
[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](docs/SETUP_GUIDE.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

RiskApp is an offline-first risk and opportunity manager: a FastAPI/SQLAlchemy API and a PySide6 desktop client with a local SQLite cache, persistent synchronization outbox, version-based conflict detection, project RBAC, audit receipts, and hashed rotating refresh tokens.

## What this repository demonstrates

- layered desktop architecture with domain services behind UI-independent adapters;
- offline operation with reliable automatic background synchronization, persistent queued writes, server receipt deduplication, and a transactional monotonic change sequence;
- a Qt Designer-backed Conflict Center that preserves unresolved writes and lets users explicitly keep the local copy, use the saved server copy, or decide later;
- authorization enforced consistently across REST and sync paths;
- Argon2id password hashing that upgrades stored hashes to new parameters at the next login;
- bounded request/response handling, literal search escaping, and safe CSV export;
- isolated API and client-core tests plus package-wide mypy, Ruff, compile, and dependency checks;
- reproducible runtime lock files and an automated CI gate.

## Architecture

See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for the components, the synchronization design, the server schema, the security model and the production trade-offs.

## Screenshots

### Risk workspace

![RiskApp main window showing the project risk workspace](docs/images/riskapp-main-window.png)

### Field-level conflict merge

![RiskApp field merge dialog comparing local and server values](docs/images/conflict-field-merge.png)

## Quick start

Install the OS packages from [step 2 of the setup guide](docs/SETUP_GUIDE.md#2-install-os-prerequisites), then run from the repository root:

```bash
bash scripts/setup_python_env.sh   # creates .venv from the lock files
bash scripts/check_project.sh      # migrations, tests, mypy, Ruff
bash scripts/dev-init.sh           # private keys and an admin password in .env
bash scripts/run_server_dev.sh     # API at http://127.0.0.1:8000, this machine only
bash scripts/run_client_dev.sh     # desktop client, in a second terminal
```

Log in with `INITIAL_SUPERUSER_EMAIL` and `INITIAL_SUPERUSER_PASSWORD` from `.env`. The interactive API documentation is at `http://127.0.0.1:8000/docs`. These commands keep existing data; the reset options in the [setup guide](docs/SETUP_GUIDE.md) delete it. The guide also explains each step and what the check runs.

CI runs the same check alongside a Trivy scan of the repository for secrets. When both pass, it builds and starts the API image, checks `/health` and scans the image: secrets and fixable high or critical vulnerabilities fail the run, and every fixable finding is reported to code scanning. CI runs on every push, on pull requests from forks and weekly. Actions are pinned by commit SHA, and a separate CodeQL workflow analyzes the Python source.

## Run the development API with Docker

The container workflow packages only the FastAPI development server. The PySide6 desktop client continues to run natively so it can use the host desktop, local cache, and normal platform integration.

From the repository root, generate local credentials and start the API:

```bash
bash scripts/dev-init.sh
docker compose up --build
```

Open `.env` locally to read `INITIAL_SUPERUSER_PASSWORD`. The login email is `INITIAL_SUPERUSER_EMAIL` in the same file, and you can change it there before the first start. Rerunning the script leaves any existing `.env` unchanged. To skip administrator creation, clear both `INITIAL_SUPERUSER_EMAIL` and `INITIAL_SUPERUSER_PASSWORD`.

Compose reads `.env` automatically. Variables exported in your shell take precedence over the file, so remove stale exports when switching configurations. Compose refuses to start with either key missing or empty. The API requires both keys to contain at least 32 characters in every environment; there is no insecure bypass. To validate the Compose configuration without printing secrets:

```bash
docker compose config --quiet
```

An existing private settings file can still be selected explicitly, for example:

```bash
docker compose --env-file .env.compose.local up --build
```

Verify it from another terminal:

```bash
curl http://127.0.0.1:8000/health
```

Then launch the native client with the existing script and log in with your own account. Its development default already points to `http://127.0.0.1:8000`. To use another host port, set both the Compose mapping and the client URL:

```bash
RISKAPP_HOST_PORT=8080 docker compose up --build
RISKAPP_URL=http://127.0.0.1:8080 bash scripts/run_client_dev.sh
```

Stop the server while retaining its data with:

```bash
docker compose down
```

Adding `--volumes` deletes the named SQLite volume and all its data.

For an existing database, changing the bootstrap variables does not change an account's password or permissions. The bootstrap variables can be cleared after the initial account is created. Replacing the signing and token-hash keys invalidates existing tokens, so users will need to log in again.

The separate test target installs the locked server and desktop dependencies, adds the Qt offscreen libraries, and runs the same migration, test, lint, compilation, and dependency checks as CI:

```bash
docker build --target test -t riskapp:test .
```

This is a local development/demo configuration, not a production deployment recipe.

## Repository map

```text
client/       PySide6 application, domain services, local store, HTTP adapter
server/       FastAPI routers, auth/RBAC, persistence, sync
tests/        Canonical headless client-core and API regression suite
scripts/      Setup, quality, run, reset, and dependency-lock workflows
docs/         Setup, testing and architecture guides
```

## Documentation

- [Setup guide](docs/SETUP_GUIDE.md): installing, running, checking and configuring RiskApp
- [Architecture](docs/ARCHITECTURE.md): components, synchronization, schema, security and trade-offs
- [Server](server/README_SERVER.md): authentication, endpoints and administration
- [Client](client/README_CLIENT.md): using the desktop app, offline modes and resolving conflicts
- [Test guide](docs/TEST_GUIDE.md): the manual verification checklist
- [Backup and recovery](docs/BACKUP_RESTORE.md): verified SQLite snapshots, recovery drills and client reconciliation limits
- [Demo rehearsal](docs/DEMO_REHEARSAL.md): isolated Windows walkthrough for offline edits, reconnect, conflicts and recovery
- [CodeQL](docs/CODEQL.md): Python source analysis and reviewing GitHub findings
- [Worker/backend contract](docs/WORKER_BACKEND_CONTRACT.md): the typed boundary used by desktop background jobs

## License

RiskApp is licensed under the [MIT License](LICENSE).

### Third-party software

RiskApp uses [PySide6 (Qt for Python)](https://doc.qt.io/qtforpython-6/), which this project uses under the GNU Lesser General Public License v3.0.

PySide6 and Qt are separate third-party works and are not covered by RiskApp's MIT License. This source repository does not bundle PySide6 or Qt binaries; they are installed separately as dependencies.
