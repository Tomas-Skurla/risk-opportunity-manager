from __future__ import annotations

import importlib
import os
import secrets
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore

# Pytest passes fixtures to tests and other fixtures by parameter name.
# pylint: disable=redefined-outer-name

# Qt must be configured before pytest-qt imports the application classes.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def isolated_app_factory(monkeypatch: pytest.MonkeyPatch):
    """Create a FastAPI app with explicit test settings and an isolated database."""
    created_engines = []

    def _make_app(
        db_url: str,
        *,
        return_reset_token: bool = False,
        max_request_body_bytes: int = 2 * 1024 * 1024,
    ):
        settings = {
            "ENV": "test",
            # Fresh random keys for every app; monkeypatch restores the
            # environment after each test.
            "SECRET_KEY": secrets.token_hex(32),
            "TOKEN_HASH_KEY": secrets.token_hex(32),
            "DATABASE_URL": db_url,
            "AUTO_CREATE_SCHEMA": "1",
            "LOGIN_RATE_LIMIT_PER_MINUTE": "2",
            "LOGIN_RATE_LIMIT_WINDOW_SECONDS": "60",
            "REFRESH_TOKEN_REUSE_GRACE_SECONDS": "30",
            "PASSWORD_RESET_RETURN_TOKEN": "1" if return_reset_token else "0",
            "MAX_REQUEST_BODY_BYTES": str(max_request_body_bytes),
            "ALLOWED_HOSTS": "*",
            "CORS_ORIGINS": "",
            "INITIAL_SUPERUSER_EMAIL": "",
            "INITIAL_SUPERUSER_PASSWORD": "",
        }
        for name, value in settings.items():
            monkeypatch.setenv(name, value)

        # Imports must follow the settings patch so reloaded modules use this test DB.
        # pylint: disable=import-outside-toplevel
        import riskapp_server.core.config as cfg

        importlib.reload(cfg)
        import riskapp_server.db.session as session

        # Reloading this module replaces its module-level SQLAlchemy engine.
        # Dispose the previous engine first so its SQLite pool is not orphaned.
        session.engine.dispose()
        importlib.reload(session)
        import riskapp_server.auth.service as auth_service

        created_engines.append(session.engine)
        importlib.reload(auth_service)

        import riskapp_server.core.permissions as permissions

        importlib.reload(permissions)

        import riskapp_server.schemas.models as schemas

        importlib.reload(schemas)

        import riskapp_server.api.routers.crud_factory as crud_factory

        importlib.reload(crud_factory)
        import riskapp_server.api.routers.auth_routes as auth_routes

        importlib.reload(auth_routes)
        import riskapp_server.api.routers.users as users

        importlib.reload(users)
        import riskapp_server.api.routers.projects as projects

        importlib.reload(projects)
        import riskapp_server.api.routers.risks as risks

        importlib.reload(risks)
        import riskapp_server.api.routers.opportunities as opportunities

        importlib.reload(opportunities)
        import riskapp_server.api.routers.items as items

        importlib.reload(items)
        import riskapp_server.api.routers.actions as actions

        importlib.reload(actions)
        import riskapp_server.api.routers.matrix as matrix

        importlib.reload(matrix)
        import riskapp_server.api.routers.snapshots as snapshots

        importlib.reload(snapshots)
        import riskapp_server.api.routers.helpdesk as helpdesk

        importlib.reload(helpdesk)
        import riskapp_server.api.routers.sync_routes as sync_routes

        importlib.reload(sync_routes)
        import riskapp_server.api.routers.admin as admin

        importlib.reload(admin)

        import riskapp_server.sync.engine as sync_engine

        importlib.reload(sync_engine)

        import riskapp_server.main.app as main_app

        # pylint: enable=import-outside-toplevel
        importlib.reload(main_app)

        return main_app.create_app()

    yield _make_app

    # Some unit tests only need modules configured for an isolated database and
    # never enter TestClient, so the FastAPI lifespan cannot perform cleanup.
    for engine in reversed(created_engines):
        engine.dispose()


@pytest.fixture
def api(tmp_path, isolated_app_factory) -> Iterator[TestClient]:
    """A client for a fresh app with its own temporary database and generated keys."""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'api.db'}")
    with TestClient(app) as client:
        yield client


@pytest.fixture
def local_store(tmp_path) -> Iterator[LocalStore]:
    """A client store with its own temporary database, closed after the test."""
    with LocalStore(str(tmp_path / "local.db")) as store:
        yield store
