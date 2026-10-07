"""Application startup, shutdown, middleware, and health boundaries."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from support import new_password

# Imports stay local to respect fixture-driven module reloads and test settings.
# pylint: disable=import-outside-toplevel


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def first(self):
        return self._value


class _FakeSession:
    def __init__(self, existing=None):
        self.existing = existing
        self.added = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _statement):
        return _ScalarResult(self.existing)

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_lifespan_awaits_initialization_and_creates_superuser(
    monkeypatch,
) -> None:
    import riskapp_server.db.session as session
    import riskapp_server.main.app as main_app

    initialized = []

    async def init_db():
        initialized.append(True)

    fake_db = _FakeSession()
    disposed = []
    monkeypatch.setattr(main_app, "init_db", init_db)
    monkeypatch.setattr(main_app, "INITIAL_SUPERUSER_EMAIL", "ROOT@Example.Test")
    monkeypatch.setattr(main_app, "INITIAL_SUPERUSER_PASSWORD", new_password())
    monkeypatch.setattr(session, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(
        main_app, "engine", SimpleNamespace(dispose=lambda: disposed.append(True))
    )

    async with main_app.lifespan(FastAPI()):
        assert initialized == [True]

    assert fake_db.commits == 1
    assert len(fake_db.added) == 1
    assert fake_db.added[0].email == "root@example.test"
    assert fake_db.added[0].is_superuser is True
    assert disposed == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("initially_active", [False, True])
@pytest.mark.parametrize("initially_superuser", [False, True])
async def test_lifespan_leaves_existing_bootstrap_account_unchanged(
    monkeypatch,
    initially_active: bool,
    initially_superuser: bool,
) -> None:
    import riskapp_server.db.session as session
    import riskapp_server.main.app as main_app

    existing = SimpleNamespace(
        is_superuser=initially_superuser,
        is_active=initially_active,
        password_hash="existing-password-hash",
    )
    fake_db = _FakeSession(existing)
    monkeypatch.setattr(main_app, "init_db", lambda: None)
    monkeypatch.setattr(main_app, "INITIAL_SUPERUSER_EMAIL", "root@example.test")
    monkeypatch.setattr(main_app, "INITIAL_SUPERUSER_PASSWORD", new_password())
    monkeypatch.setattr(session, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(main_app, "engine", SimpleNamespace(dispose=lambda: None))

    async with main_app.lifespan(FastAPI()):
        pass

    assert existing.is_superuser is initially_superuser
    assert existing.is_active is initially_active
    assert existing.password_hash == "existing-password-hash"
    assert not fake_db.added
    assert fake_db.commits == 0


@pytest.mark.asyncio
async def test_lifespan_rejects_weak_bootstrap_password_and_logs_dispose_failures(
    monkeypatch,
) -> None:
    import riskapp_server.main.app as main_app

    logged = []

    def fail_dispose():
        raise RuntimeError("dispose failed")

    monkeypatch.setattr(main_app, "init_db", lambda: None)
    monkeypatch.setattr(main_app, "INITIAL_SUPERUSER_EMAIL", "root@example.test")
    monkeypatch.setattr(main_app, "INITIAL_SUPERUSER_PASSWORD", "weak")
    monkeypatch.setattr(main_app, "engine", SimpleNamespace(dispose=fail_dispose))
    monkeypatch.setattr(main_app.logger, "exception", logged.append)

    with pytest.raises(RuntimeError, match="does not satisfy password policy"):
        async with main_app.lifespan(FastAPI()):
            pass

    assert logged == ["Application startup failed", "DB engine dispose failed"]


def test_create_app_optional_middleware_and_health_states(
    monkeypatch, tmp_path, isolated_app_factory
) -> None:
    import riskapp_server.main.app as main_app

    monkeypatch.setattr(main_app, "CORS_ORIGINS", ["https://app.example.test"])
    monkeypatch.setattr(main_app, "GZIP_ENABLED", False)
    monkeypatch.setattr(main_app, "ALLOWED_HOSTS", [])
    monkeypatch.setattr(main_app, "validate_runtime_config", lambda: None)
    configured = main_app.create_app()
    middleware_names = {
        getattr(entry.cls, "__name__")  # noqa: B009 - FastAPI allows factories
        for entry in configured.user_middleware
    }
    assert "CORSMiddleware" in middleware_names
    assert "GZipMiddleware" not in middleware_names
    assert "TrustedHostMiddleware" not in middleware_names

    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'health.db'}")
    with TestClient(app) as client:
        healthy = client.get("/health")
        assert healthy.status_code == 200
        assert healthy.json() == {"status": "ok", "db": "ok"}

        import riskapp_server.db.session as session

        class FailingDb:
            def execute(self, _statement):
                raise RuntimeError("database unavailable")

        def failing_db():
            yield FailingDb()

        app.dependency_overrides[session.get_db] = failing_db
        degraded = client.get("/health")
        assert degraded.status_code == 503
        assert degraded.json() == {"status": "degraded", "db": "unreachable"}


def test_server_entrypoint_environment_flags(monkeypatch) -> None:
    from riskapp_server import __main__ as server_main

    run = Mock()
    monkeypatch.setattr("uvicorn.run", run)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("RISKAPP_HOST", "0.0.0.0")
    monkeypatch.setenv("RISKAPP_PORT", "9000")
    monkeypatch.setenv("RISKAPP_RELOAD", "yes")
    assert server_main.main() == 0
    run.assert_called_once_with(
        "riskapp_server.main.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=9000,
        reload=True,
    )
    monkeypatch.delenv("RISKAPP_RELOAD")
    # pylint: disable-next=protected-access
    assert server_main._env_flag("RISKAPP_RELOAD", False) is False


@pytest.mark.asyncio
async def test_https_middleware_allows_rejects_and_honors_forwarded_proto(
    monkeypatch,
) -> None:
    from riskapp_server.main import https_only_middleware
    from starlette.requests import Request
    from starlette.responses import Response

    middleware = object.__new__(https_only_middleware.HttpsOnlyMiddleware)
    next_response = Response("next")

    async def call_next(_request: Request) -> Response:
        return next_response

    request_double = SimpleNamespace(
        url=SimpleNamespace(scheme="http"),
        headers={},
    )
    request = cast(Request, request_double)

    monkeypatch.setattr(https_only_middleware, "ENFORCE_HTTPS", False)
    assert await middleware.dispatch(request, call_next) is next_response

    monkeypatch.setattr(https_only_middleware, "ENFORCE_HTTPS", True)
    monkeypatch.setattr(https_only_middleware, "TRUST_X_FORWARDED_PROTO", False)
    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 400

    monkeypatch.setattr(https_only_middleware, "TRUST_X_FORWARDED_PROTO", True)
    request_double.headers = {"x-forwarded-proto": "HTTPS, http"}
    assert await middleware.dispatch(request, call_next) is next_response
