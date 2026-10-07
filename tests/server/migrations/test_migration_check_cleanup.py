"""Migration validation must release SQLite handles before temporary cleanup."""

from __future__ import annotations

import importlib.util
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from support import REPO_ROOT


@pytest.mark.parametrize("schema", ["valid", "missing_revision", "missing_table"])
def test_checker_closes_validation_database_on_success_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, schema: str
) -> None:
    spec = importlib.util.spec_from_file_location(
        "migration_checker", REPO_ROOT / "scripts" / "check_migrations.py"
    )
    assert spec is not None and spec.loader is not None
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    monkeypatch.setattr(checker, "_temporary_parent", lambda: tmp_path)
    connect = sqlite3.connect
    opened: list[sqlite3.Connection] = []

    def prepare_schema(_arguments: list[str], environment: dict[str, str]) -> None:
        database_path = Path(
            environment["DATABASE_URL"].removeprefix("sqlite+pysqlite:///")
        )
        if database_path.exists():
            return
        with closing(connect(database_path)) as connection:
            if schema != "missing_table":
                connection.execute("CREATE TABLE alembic_version (version_num TEXT)")
                if schema == "valid":
                    connection.execute("INSERT INTO alembic_version VALUES ('0003')")
                connection.commit()

    def track_connection(database_path: Path) -> sqlite3.Connection:
        connection = connect(database_path)
        opened.append(connection)
        return connection

    monkeypatch.setattr(checker, "_run_alembic", prepare_schema)
    monkeypatch.setattr(checker.sqlite3, "connect", track_connection)

    try:
        if schema == "valid":
            assert checker.main() == 0
        elif schema == "missing_revision":
            with pytest.raises(RuntimeError, match="did not record a schema revision"):
                checker.main()
        else:
            with pytest.raises(sqlite3.OperationalError, match="no such table"):
                checker.main()

        assert len(opened) == 1
        # Retain a reference so garbage collection cannot hide a leaked handle
        # on platforms that permit unlinking an open database file.
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            opened[0].execute("SELECT 1")
        assert list(tmp_path.iterdir()) == []
    finally:
        for connection in opened:
            connection.close()
