"""Application startup, shutdown, middleware, and health boundaries."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


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
    monkeypatch.setattr(main_app, "INITIAL_SUPERUSER_PASSWORD", "Password123!")
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
async def test_lifespan_promotes_existing_superuser(
    monkeypatch, initially_active: bool
) -> None:
    import riskapp_server.db.session as session
    import riskapp_server.main.app as main_app

    existing = SimpleNamespace(is_superuser=False, is_active=initially_active)
    fake_db = _FakeSession(existing)
    monkeypatch.setattr(main_app, "init_db", lambda: None)
    monkeypatch.setattr(main_app, "INITIAL_SUPERUSER_EMAIL", "root@example.test")
    monkeypatch.setattr(main_app, "INITIAL_SUPERUSER_PASSWORD", "Password123!")
    monkeypatch.setattr(session, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(main_app, "engine", SimpleNamespace(dispose=lambda: None))

    async with main_app.lifespan(FastAPI()):
        pass

    assert existing.is_superuser is True
    assert existing.is_active is True
    assert fake_db.commits == 1


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
    monkeypatch.setattr(
        main_app.logger, "exception", lambda message: logged.append(message)
    )

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
    middleware_names = {entry.cls.__name__ for entry in configured.user_middleware}
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
