from __future__ import annotations

import pytest


@pytest.mark.usefixtures("api")
def test_server_sqlite_connections_enforce_foreign_keys() -> None:
    """Every server SQLite connection enables declared FK constraints."""
    # The engine must be the one created for the api fixture's app.
    # pylint: disable-next=import-outside-toplevel
    from riskapp_server.db.session import engine

    with engine.connect() as connection:
        enabled = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
    assert enabled == 1
