from __future__ import annotations

import ast
import functools
import importlib
import os
import secrets
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore

# Pytest passes fixtures to tests and other fixtures by parameter name.
# pylint: disable=redefined-outer-name

# Qt must be configured before pytest-qt imports the application classes.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@functools.cache
def _names_imported_from_config(module_file: str) -> frozenset[str]:
    """The names a server module copies with ``from ...core.config import``."""
    tree = ast.parse(Path(module_file).read_text(encoding="utf-8"))
    return frozenset(
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "riskapp_server.core.config"
        for alias in node.names
    )


def _refresh_copied_settings(cfg) -> None:
    """Give every loaded server module the settings of the freshly reloaded config.

    Modules copy settings at import, so after reloading the config their copies
    are stale. Updating the copies in place keeps every function and class the
    same object for the whole test run, unlike reloading those modules.
    """
    for name, module in list(sys.modules.items()):
        if not name.startswith("riskapp_server.") or module is cfg:
            continue
        module_file = getattr(module, "__file__", None)
        if not module_file or not module_file.endswith(".py"):
            continue
        for setting in _names_imported_from_config(module_file):
            setattr(module, setting, getattr(cfg, setting))


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

        # Imports must follow the settings patch so they see this test's settings.
        # pylint: disable=import-outside-toplevel
        import riskapp_server.core.config as cfg

        importlib.reload(cfg)
        _refresh_copied_settings(cfg)

        # Point the session module at this test's database. Reloading it instead
        # would re-create every model class, and every module importing one.
        import riskapp_server.db.session as session

        session.engine.dispose()
        session.engine = session.create_db_engine(db_url)
        session.SessionLocal.configure(bind=session.engine)
        created_engines.append(session.engine)

        # These routers build rate limiters from settings at import, so a fresh
        # import also gives each test fresh limits and empty counters. main.app
        # then picks up their new routers and the new engine.
        import riskapp_server.api.routers.auth_routes as auth_routes
        import riskapp_server.api.routers.users as users
        import riskapp_server.main.app as main_app

        # pylint: enable=import-outside-toplevel
        for module in (auth_routes, users, main_app):
            importlib.reload(module)

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
