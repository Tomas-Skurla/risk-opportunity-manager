"""Recovery drills use migrated databases, live WAL writes, and real API data."""

from __future__ import annotations

import errno
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from riskapp_server.ops import sqlite_backup as backups
from support import REPO_ROOT, create_project, new_change, pull, push, register_user


@pytest.fixture(name="migrated_template", scope="module")
def _migrated_template(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("backup-template") / "server.sqlite3"
    environment = os.environ.copy()
    environment.update(
        ENV="test",
        SECRET_KEY=secrets.token_hex(32),
        TOKEN_HASH_KEY=secrets.token_hex(32),
        AUTO_CREATE_SCHEMA="0",
        DATABASE_URL=f"sqlite+pysqlite:///{path.as_posix()}",
    )
    subprocess.run(  # noqa: S603 - fixed interpreter and migration command
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return path


@pytest.fixture(name="database")
def _database(tmp_path: Path, migrated_template: Path) -> Path:
    path = tmp_path / "server with spaces.sqlite3"
    backups.backup_database(migrated_template, path)
    return path


def _rows(path: Path, table: str) -> list[tuple]:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(
            f'SELECT * FROM "{table}" ORDER BY 1'  # noqa: S608 - fixed test table names
        ).fetchall()


def test_online_backup_includes_committed_wal_data_and_preserves_source(
    database: Path, tmp_path: Path
) -> None:
    snapshot = tmp_path / "snapshot.sqlite3"
    with closing(sqlite3.connect(database)) as live:
        assert live.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        live.execute("PRAGMA wal_autocheckpoint=0")
        live.execute(
            "INSERT INTO users (id,email,password_hash,is_active,is_superuser) "
            "VALUES (?,?,?,?,?)",
            (uuid.uuid4().hex, "wal@example.test", "hash", 1, 0),
        )
        live.commit()
        assert Path(str(database) + "-wal").stat().st_size > 0
        info = backups.backup_database(database, snapshot)
        assert _rows(snapshot, "users") == _rows(database, "users")
        assert live.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert info == backups.verify_backup(snapshot)
    assert len(info.sha256) == 64
    assert not any(Path(str(snapshot) + suffix).exists() for suffix in ("-wal", "-shm"))
    if os.name != "nt":
        assert snapshot.stat().st_mode & 0o777 == 0o600


def test_recovery_restores_authentication_receipts_and_sequence_counters(
    database: Path, tmp_path: Path, isolated_app_factory, monkeypatch
) -> None:
    snapshot = tmp_path / "recovery.sqlite3"
    app = isolated_app_factory(f"sqlite+pysqlite:///{database.as_posix()}")
    # Import after the factory reloads authentication with this test's settings.
    # pylint: disable-next=import-outside-toplevel
    from riskapp_server.auth import service as auth_service

    saved_signing_key = auth_service.SECRET_KEY
    saved_token_key = auth_service.TOKEN_HASH_KEY
    ticket_id = str(uuid.uuid4())
    change = new_change("helpdesk_ticket", {"id": ticket_id, "title": "Recover me"})
    with TestClient(app) as client:
        user = register_user(client)
        project = create_project(client, user, name="Recovery project")
        accepted = push(client, project.id, user, change)
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["results"][0]["status"] == "accepted"
        backups.backup_database(database, snapshot)
        snapshot_rows = {
            table: _rows(snapshot, table)
            for table in (
                "users",
                "projects",
                "project_members",
                "refresh_tokens",
                "helpdesk_tickets",
                "sync_receipts",
                "sync_project_state",
                "audit_log",
            )
        }
        create_project(client, user, name="After snapshot")
    assert len(_rows(database, "projects")) == 2

    restored = backups.restore_database(snapshot, database, offline=True, replace=True)
    assert restored.revision == backups.verify_backup(snapshot).revision
    for table, rows in snapshot_rows.items():
        assert _rows(database, table) == rows
    recovered_app = isolated_app_factory(f"sqlite+pysqlite:///{database.as_posix()}")
    monkeypatch.setattr(auth_service, "SECRET_KEY", saved_signing_key)
    monkeypatch.setattr(auth_service, "TOKEN_HASH_KEY", saved_token_key)
    with TestClient(recovered_app) as client:
        assert client.get("/users/me", headers=user.headers).status_code == 200
        response = client.post("/refresh", json={"refresh_token": user.refresh_token})
        assert response.status_code == 200, response.text
        logged_in = client.post(
            "/login", data={"username": user.email, "password": user.password}
        )
        assert logged_in.status_code == 200, logged_in.text
        replay = push(client, project.id, user, change)
        assert replay.status_code == 200, replay.text
        assert replay.json()["results"][0]["replayed"] is True
        assert (
            _rows(database, "sync_project_state") == snapshot_rows["sync_project_state"]
        )
        second = new_change(
            "helpdesk_ticket", {"id": str(uuid.uuid4()), "title": "After recovery"}
        )
        assert (
            push(client, project.id, user, second).json()["results"][0]["status"]
            == "accepted"
        )
        pulled = pull(client, project.id, user)
        assert pulled.status_code == 200, pulled.text
        assert {ticket["title"] for ticket in pulled.json()["helpdesk_tickets"]} == {
            "Recover me",
            "After recovery",
        }
        assert (
            _rows(database, "sync_project_state")[0][1]
            == snapshot_rows["sync_project_state"][0][1] + 1
        )


@pytest.mark.parametrize("sidecar", ["-wal", "-shm", "-journal"])
def test_restore_refuses_sidecars_and_preserves_target(
    database: Path, tmp_path: Path, sidecar: str
) -> None:
    snapshot = tmp_path / "snapshot.sqlite3"
    backups.backup_database(database, snapshot)
    original = database.read_bytes()
    Path(str(database) + sidecar).write_bytes(b"keep")
    with pytest.raises(backups.BackupError, match="sidecars"):
        backups.restore_database(snapshot, database, offline=True, replace=True)
    assert database.read_bytes() == original
    assert Path(str(database) + sidecar).read_bytes() == b"keep"


def test_restore_requires_offline_and_explicit_replacement(
    database: Path, tmp_path: Path
) -> None:
    snapshot = tmp_path / "snapshot.sqlite3"
    backups.backup_database(database, snapshot)
    original = database.read_bytes()
    with pytest.raises(backups.BackupError, match="--offline"):
        backups.restore_database(snapshot, database, replace=True)
    with pytest.raises(backups.BackupError, match="Destination exists"):
        backups.restore_database(snapshot, database, offline=True)
    assert database.read_bytes() == original
    fresh = tmp_path / "fresh.sqlite3"
    assert backups.restore_database(snapshot, fresh, offline=True).revision


@pytest.mark.parametrize(
    "problem", ["corrupt", "wrong_revision", "foreign_key", "unmigrated"]
)
def test_bad_snapshots_are_rejected_without_changing_target(
    database: Path, tmp_path: Path, problem: str
) -> None:
    snapshot = tmp_path / "bad.sqlite3"
    backups.backup_database(database, snapshot)
    if problem == "corrupt":
        snapshot.write_bytes(b"not sqlite")
    else:
        with closing(sqlite3.connect(snapshot)) as connection:
            if problem == "wrong_revision":
                connection.execute("UPDATE alembic_version SET version_num='0001'")
            elif problem == "foreign_key":
                connection.execute(
                    "INSERT INTO sync_project_state (project_id,last_sequence) VALUES (?,?)",
                    (uuid.uuid4().hex, 1),
                )
            else:
                connection.execute("DROP TABLE sync_receipts")
            connection.commit()
    original = database.read_bytes()
    with pytest.raises((backups.BackupError, sqlite3.DatabaseError)):
        backups.restore_database(snapshot, database, offline=True, replace=True)
    assert database.read_bytes() == original
    assert not list(tmp_path.glob(".riskapp-*"))


def test_backup_refuses_missing_identical_and_existing_paths(
    database: Path, tmp_path: Path
) -> None:
    destination = tmp_path / "new.sqlite3"
    with pytest.raises(backups.BackupError, match="existing regular file"):
        backups.backup_database(tmp_path / "missing.sqlite3", destination)
    assert not destination.exists()
    with pytest.raises(backups.BackupError, match="different files"):
        backups.backup_database(database, database)
    destination.write_bytes(b"previous backup")
    with pytest.raises(backups.BackupError, match="Destination exists"):
        backups.backup_database(database, destination)
    assert destination.read_bytes() == b"previous backup"
    with pytest.raises(backups.BackupError, match="directory must already exist"):
        backups.backup_database(database, tmp_path / "missing" / "backup.sqlite3")


def test_backup_timeout_leaves_no_published_file(
    database: Path, tmp_path: Path, monkeypatch
) -> None:
    snapshot = tmp_path / "snapshot.sqlite3"
    times = iter([0.0, 31.0])
    monkeypatch.setattr(backups.time, "monotonic", lambda: next(times))
    with pytest.raises(backups.BackupError, match="timed out"):
        backups.backup_database(database, snapshot)
    assert not snapshot.exists()
    assert not list(tmp_path.glob(".riskapp-*"))


@pytest.mark.parametrize("operation", ["backup", "restore"])
def test_snapshot_flush_has_write_access_before_publication(
    database: Path, tmp_path: Path, monkeypatch, operation: str
) -> None:
    destination = tmp_path / "flushed.sqlite3"
    original = database.read_bytes()
    real_fsync, real_link = os.fsync, os.link
    flushes = []

    def require_write_access(descriptor):
        # A zero-byte write verifies access without changing the snapshot.
        # Linux otherwise permits fsync on a read-only descriptor; Windows does not.
        os.write(descriptor, b"")
        real_fsync(descriptor)
        flushes.append(descriptor)

    def publish(source, target):
        assert len(flushes) == 1
        real_link(source, target)

    monkeypatch.setattr(backups.os, "fsync", require_write_access)
    monkeypatch.setattr(backups.os, "link", publish)
    if operation == "backup":
        info = backups.backup_database(database, destination)
    else:
        info = backups.restore_database(database, destination, offline=True)
    assert info == backups.verify_backup(destination)
    assert database.read_bytes() == original
    assert _rows(destination, "users") == _rows(database, "users")
    assert not list(tmp_path.glob(".riskapp-*"))


@pytest.mark.parametrize("operation", ["backup", "restore", "replace"])
def test_failed_snapshot_flush_keeps_destination_unchanged(
    database: Path, tmp_path: Path, monkeypatch, operation: str
) -> None:
    destination = tmp_path / "destination.sqlite3"
    source_bytes = database.read_bytes()
    previous = None
    if operation == "replace":
        backups.backup_database(database, destination)
        with closing(sqlite3.connect(destination)) as connection:
            connection.execute(
                "INSERT INTO users (id,email,password_hash,is_active,is_superuser) "
                "VALUES (?,?,?,?,?)",
                (uuid.uuid4().hex, "keep@example.test", "hash", 1, 0),
            )
            connection.commit()
        previous = destination.read_bytes()

    def failed_flush(_descriptor):
        raise OSError(errno.EIO, "Disk flush failed")

    monkeypatch.setattr(backups.os, "fsync", failed_flush)
    with pytest.raises(OSError, match="Disk flush failed"):
        if operation == "backup":
            backups.backup_database(database, destination)
        else:
            backups.restore_database(
                database, destination, offline=True, replace=operation == "replace"
            )
    if previous is None:
        assert not destination.exists()
    else:
        assert destination.read_bytes() == previous
    assert database.read_bytes() == source_bytes
    assert not list(tmp_path.glob(".riskapp-*"))


def test_locked_database_times_out_without_publishing(
    database: Path, tmp_path: Path
) -> None:
    snapshot = tmp_path / "locked.sqlite3"
    with closing(sqlite3.connect(database)) as writer:
        writer.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        with pytest.raises(backups.BackupError, match="timed out"):
            backups.backup_database(database, snapshot, timeout=0.1)
        assert time.monotonic() - started < 5
        writer.rollback()
    assert not snapshot.exists()
    assert not list(tmp_path.glob(".riskapp-*"))
    assert backups.backup_database(database, snapshot).revision


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeout_never_publishes_a_snapshot(
    database: Path, tmp_path: Path, timeout: float
) -> None:
    snapshot = tmp_path / "invalid-timeout.sqlite3"
    with pytest.raises(backups.BackupError, match="finite and positive"):
        backups.backup_database(database, snapshot, timeout=timeout)
    assert not snapshot.exists()
    assert not list(tmp_path.glob(".riskapp-*"))


def test_racing_backup_cannot_overwrite_another_snapshot(
    database: Path, tmp_path: Path, monkeypatch
) -> None:
    snapshot = tmp_path / "winner.sqlite3"
    original_link = os.link

    def publish_after_another_backup(source, destination):
        Path(destination).write_bytes(b"completed by another process")
        original_link(source, destination)

    monkeypatch.setattr(backups.os, "link", publish_after_another_backup)
    with pytest.raises(FileExistsError):
        backups.backup_database(database, snapshot)
    assert snapshot.read_bytes() == b"completed by another process"
    assert not list(tmp_path.glob(".riskapp-*"))


def test_failed_restore_replacement_keeps_original_database(
    database: Path, tmp_path: Path, monkeypatch
) -> None:
    snapshot = tmp_path / "snapshot.sqlite3"
    backups.backup_database(database, snapshot)
    original = database.read_bytes()

    def locked_destination(_source, _destination):
        raise PermissionError("Destination is locked")

    monkeypatch.setattr(backups.os, "replace", locked_destination)
    with pytest.raises(PermissionError):
        backups.restore_database(snapshot, database, offline=True, replace=True)
    assert database.read_bytes() == original
    assert not list(tmp_path.glob(".riskapp-*"))


def test_restore_rechecks_sidecars_after_staging(
    database: Path, tmp_path: Path, monkeypatch
) -> None:
    snapshot = tmp_path / "snapshot.sqlite3"
    backups.backup_database(database, snapshot)
    original = database.read_bytes()
    # Inject a worker reopening the target between staging and publication.
    # pylint: disable-next=protected-access
    copy_snapshot = backups._copy_snapshot

    def a_worker_reopened_the_target(*args, **kwargs):
        result = copy_snapshot(*args, **kwargs)
        Path(str(database) + "-wal").write_bytes(b"worker reopened database")
        return result

    monkeypatch.setattr(backups, "_copy_snapshot", a_worker_reopened_the_target)
    with pytest.raises(backups.BackupError, match="sidecars"):
        backups.restore_database(snapshot, database, offline=True, replace=True)
    assert database.read_bytes() == original
    assert not list(tmp_path.glob(".riskapp-*"))


def test_hard_link_alias_cannot_replace_the_source(
    database: Path, tmp_path: Path
) -> None:
    alias = tmp_path / "alias.sqlite3"
    os.link(database, alias)
    original = database.read_bytes()
    with pytest.raises(backups.BackupError, match="different files"):
        backups.restore_database(database, alias, offline=True, replace=True)
    assert database.read_bytes() == original


def test_automatic_schema_requires_explicit_unversioned_opt_in(
    tmp_path: Path, isolated_app_factory, capsys
) -> None:
    database = tmp_path / "automatic.sqlite3"
    app = isolated_app_factory(f"sqlite+pysqlite:///{database.as_posix()}")
    with TestClient(app) as client:
        register_user(client)
    snapshot = tmp_path / "development.sqlite3"
    with pytest.raises(backups.BackupError, match="--allow-unversioned"):
        backups.backup_database(database, snapshot)
    assert not snapshot.exists()
    assert (
        backups.main(
            [
                "backup",
                "--database",
                str(database),
                "--output",
                str(snapshot),
                "--allow-unversioned",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["revision"] is None
    with pytest.raises(backups.BackupError, match="--allow-unversioned"):
        backups.verify_backup(snapshot)
    assert backups.verify_backup(snapshot, allow_unversioned=True).revision is None
    restored = tmp_path / "development-restored.sqlite3"
    with pytest.raises(backups.BackupError, match="--allow-unversioned"):
        backups.restore_database(snapshot, restored, offline=True)
    backups.restore_database(snapshot, restored, offline=True, allow_unversioned=True)
    assert _rows(restored, "users") == _rows(database, "users")
    with closing(sqlite3.connect(snapshot)) as connection:
        connection.execute("ALTER TABLE sync_receipts DROP COLUMN payload_hash")
        connection.commit()
    with pytest.raises(backups.BackupError, match="current sync columns"):
        backups.verify_backup(snapshot, allow_unversioned=True)


def test_unversioned_option_cannot_bypass_a_wrong_migration_revision(
    database: Path, tmp_path: Path
) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE alembic_version SET version_num='0001'")
        connection.commit()
    snapshot = tmp_path / "older.sqlite3"
    with pytest.raises(backups.BackupError, match="migration head"):
        backups.backup_database(database, snapshot, allow_unversioned=True)
    assert not snapshot.exists()


def test_cli_backup_verify_restore_and_safe_errors(
    database: Path, tmp_path: Path, capsys
) -> None:
    snapshot = tmp_path / "cli.sqlite3"
    assert (
        backups.main(["backup", "--database", str(database), "--output", str(snapshot)])
        == 0
    )
    first = json.loads(capsys.readouterr().out)
    assert backups.main(["verify", "--backup", str(snapshot)]) == 0
    assert json.loads(capsys.readouterr().out) == first
    restored = tmp_path / "restored.sqlite3"
    assert (
        backups.main(
            [
                "restore",
                "--backup",
                str(snapshot),
                "--database",
                str(restored),
                "--offline",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["revision"] == first["revision"]
    assert (
        backups.main(["backup", "--database", str(database), "--output", str(snapshot)])
        == 1
    )
    assert "Destination exists" in capsys.readouterr().err
    result = (
        subprocess.run(  # noqa: S603 - fixed repository wrapper in an isolated test
            [
                sys.executable,
                str(REPO_ROOT / "scripts/server_database.py"),
                "verify",
                "--backup",
                str(snapshot),
            ],
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
        )
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["sha256"] == first["sha256"]
