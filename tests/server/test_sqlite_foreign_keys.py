from __future__ import annotations

from fastapi.testclient import TestClient


def test_server_sqlite_connections_enforce_foreign_keys(
    tmp_path, isolated_app_factory
) -> None:
    """Every server SQLite connection enables declared FK constraints."""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'fk.db'}")
    with TestClient(app):
        from riskapp_server.db.session import engine

        with engine.connect() as connection:
            enabled = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
        assert enabled == 1
