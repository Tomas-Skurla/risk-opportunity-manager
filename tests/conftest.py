from __future__ import annotations

import importlib
import os

import pytest

# Qt must be configured before pytest-qt imports the application classes.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def isolated_app_factory(monkeypatch: pytest.MonkeyPatch):
    """Create a FastAPI app with explicit test settings and an isolated database."""

    def _make_app(
        db_url: str,
        *,
        return_reset_token: bool = False,
        max_request_body_bytes: int = 2 * 1024 * 1024,
    ):
        settings = {
            "ENV": "test",
            "SECRET_KEY": "riskapp-test-secret-key-that-is-not-used-in-production",
            "ALLOW_INSECURE_DEFAULT_SECRET": "0",
            "DATABASE_URL": db_url,
            "AUTO_CREATE_SCHEMA": "1",
            "LOGIN_RATE_LIMIT_PER_MINUTE": "2",
            "LOGIN_RATE_LIMIT_WINDOW_SECONDS": "60",
            "PASSWORD_RESET_RETURN_TOKEN": "1" if return_reset_token else "0",
            "PBKDF2_ITERS": "100000",
            "MAX_REQUEST_BODY_BYTES": str(max_request_body_bytes),
            "ALLOWED_HOSTS": "*",
            "CORS_ORIGINS": "",
            "INITIAL_SUPERUSER_EMAIL": "",
            "INITIAL_SUPERUSER_PASSWORD": "",
        }
        for name, value in settings.items():
            monkeypatch.setenv(name, value)

        import riskapp_server.core.config as cfg

        importlib.reload(cfg)
        import riskapp_server.db.session as session

        importlib.reload(session)
        import riskapp_server.auth.service as auth_service

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

        import riskapp_server.sync.engine as sync_engine

        importlib.reload(sync_engine)

        import riskapp_server.main.app as main_app

        importlib.reload(main_app)

        return main_app.create_app()

    return _make_app
