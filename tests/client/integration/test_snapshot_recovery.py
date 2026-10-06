"""Rehearse a server rollback while keeping later client data recoverable."""

from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
from riskapp_client.services.offline_first_facade import OfflineFirstBackend
from riskapp_server.ops.sqlite_backup import backup_database, restore_database
from support import User, create_project, pull, push, register_user


class _RequestError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class _Remote:
    """Connect the actual client coordinator to the recovered API."""

    def __init__(self, client: TestClient, user: User) -> None:
        self.client = client
        self.user = user

    @staticmethod
    def _body(response) -> dict[str, Any]:
        body = response.json()
        if response.status_code >= 400:
            raise _RequestError(response.status_code, str(body["detail"]))
        return body

    def sync_push(self, project_id: str, changes: list[dict]) -> dict[str, Any]:
        return self._body(push(self.client, project_id, self.user, *changes))

    def sync_pull(self, project_id: str, **options: Any) -> dict[str, Any]:
        return self._body(pull(self.client, project_id, self.user, **options))


def _backend(path: Path, project_id: str, remote: _Remote) -> OfflineFirstBackend:
    store = LocalStore(str(path))
    store.create_local_project(name="Recovery drill", project_id=project_id)
    return OfflineFirstBackend(store, remote=remote)


@dataclass(frozen=True)
class _Recovery:
    project_id: str
    risk_id: str
    later_risk_id: str
    client_db: Path
    clean_client_db: Path
    backup_sequence: int
    client_sequence: int
    queued: dict[str, Any]
    remote: _Remote


@pytest.fixture(name="recovery")
def _recovery(tmp_path: Path, isolated_app_factory, monkeypatch):
    database = tmp_path / "server.sqlite3"
    snapshot = tmp_path / "earlier.sqlite3"
    client_db = tmp_path / "original-client.sqlite3"
    clean_client_db = tmp_path / "original-clean-client.sqlite3"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    app = isolated_app_factory(url)
    # Import after the factory reloads authentication with this test's settings.
    # pylint: disable-next=import-outside-toplevel
    from riskapp_server.auth import service as auth_service

    signing_key, token_key = auth_service.SECRET_KEY, auth_service.TOKEN_HASH_KEY
    with TestClient(app) as client:
        user = register_user(client)
        project_id = create_project(client, user, name="Snapshot recovery").id
        remote = _Remote(client, user)
        original = _backend(client_db, project_id, remote)
        clean = _backend(clean_client_db, project_id, remote)
        try:
            risk = original.create_risk(
                project_id, title="At backup", probability=2, impact=3
            )
            assert original.sync_project(project_id)["state"] == "complete"
            backup_sequence = original.store.get_last_server_sequence(project_id)
            backup_database(database, snapshot, allow_unversioned=True)

            original.update_risk(
                project_id,
                risk.id,
                title="Accepted after backup",
                probability=3,
                impact=3,
            )
            later = original.create_risk(
                project_id, title="Exists only after backup", probability=1, impact=2
            )
            assert original.sync_project(project_id)["state"] == "complete"
            assert clean.sync_project(project_id)["state"] == "complete"
            client_sequence = original.store.get_last_server_sequence(project_id)
            assert client_sequence > backup_sequence

            # This edit remains local; it has never been sent to the server.
            original.update_risk(
                project_id,
                risk.id,
                title="Queued offline draft",
                probability=5,
                impact=4,
            )
            queued = original.outbox.get_pending_changes(project_id)[0]
            assert queued["base_version"] == 2
        finally:
            original.store.close()
            clean.store.close()

    restore_database(
        snapshot, database, offline=True, replace=True, allow_unversioned=True
    )
    recovered_app = isolated_app_factory(url)
    # Database recovery retains the original deployment's private keys.
    monkeypatch.setattr(auth_service, "SECRET_KEY", signing_key)
    monkeypatch.setattr(auth_service, "TOKEN_HASH_KEY", token_key)
    with TestClient(recovered_app) as client:
        remote = _Remote(client, user)
        restored = remote.sync_pull(project_id, since_sequence=0)
        assert restored["server_sequence"] == backup_sequence
        assert {row["id"] for row in restored["risks"]} == {risk.id}
        yield _Recovery(
            project_id,
            risk.id,
            later.id,
            client_db,
            clean_client_db,
            backup_sequence,
            client_sequence,
            queued,
            remote,
        )


def test_older_snapshot_reports_stale_cursor_and_preserves_queued_work(
    recovery,
) -> None:
    original = OfflineFirstBackend(
        LocalStore(str(recovery.client_db)), remote=recovery.remote
    )
    try:
        summary = original.sync_project(recovery.project_id)
        assert summary["state"] == "attention_required"
        assert summary["sync_error"]["http_status"] == 400
        assert (
            "snapshot_sequence precedes since_sequence"
            in summary["sync_error"]["detail"]
        )
        assert (
            original.store.get_last_server_sequence(recovery.project_id)
            == recovery.client_sequence
        )
        conflicts = original.conflict_details(recovery.project_id)
        assert len(conflicts) == 1
        assert conflicts[0]["change_id"] == recovery.queued["change_id"]
        assert conflicts[0]["base_version"] == 2
        assert conflicts[0]["server_version"] == 1
        assert conflicts[0]["record"] == recovery.queued["record"]
        row = original.store.get_risk_row(recovery.risk_id)
        assert row is not None
        assert row["title"] == "Queued offline draft"
    finally:
        original.store.close()


def test_resetting_only_the_cursor_keeps_later_cached_entities(recovery) -> None:
    clean = OfflineFirstBackend(
        LocalStore(str(recovery.clean_client_db)), remote=recovery.remote
    )
    try:
        assert clean.pending_count(recovery.project_id) == 0
        clean.store.reset_sync_watermark(recovery.project_id, "1970-01-01T00:00:00")
        assert clean.sync_project(recovery.project_id)["state"] == "complete"
        # Incremental application is not replacement of the whole local cache.
        assert clean.store.get_risk_row(recovery.later_risk_id) is not None
        assert (
            clean.store.get_last_server_sequence(recovery.project_id)
            == recovery.backup_sequence
        )
    finally:
        clean.store.close()


def test_fresh_cache_recovery_reapplies_selected_work_and_keeps_original(
    recovery, tmp_path
) -> None:
    original_bytes = recovery.client_db.read_bytes()
    archive = tmp_path / "preserved-client.sqlite3"
    # The client was closed above; copying its file is safe only in that state.
    assert not Path(str(recovery.client_db) + "-wal").exists()
    shutil.copy2(recovery.client_db, archive)
    fresh = _backend(
        tmp_path / "recovered-client.sqlite3", recovery.project_id, recovery.remote
    )
    try:
        assert fresh.sync_project(recovery.project_id)["state"] == "complete"
        rows = fresh.list_risks(recovery.project_id)
        assert {row.id for row in rows} == {recovery.risk_id}
        assert rows[0].title == "At backup"
        assert rows[0].version == 1
        assert fresh.pending_count(recovery.project_id) == 0

        # Re-enter the explicitly selected fields against the restored version;
        # do not replay an old payload/change ID or silently change its base.
        saved = recovery.queued["record"]
        fresh.update_risk(
            recovery.project_id,
            recovery.risk_id,
            title=saved["title"],
            probability=saved["probability"],
            impact=saved["impact"],
        )
        pending = fresh.outbox.get_pending_changes(recovery.project_id)
        assert pending[0]["change_id"] != recovery.queued["change_id"]
        assert pending[0]["base_version"] == 1
        assert fresh.sync_project(recovery.project_id)["state"] == "complete"
        assert fresh.pending_count(recovery.project_id) == 0
        server_row = recovery.remote.sync_pull(recovery.project_id, since_sequence=0)[
            "risks"
        ][0]
        assert server_row["title"] == "Queued offline draft"
        assert server_row["probability"] == 5
        assert server_row["impact"] == 4
        assert server_row["version"] == 2
    finally:
        fresh.store.close()
    assert recovery.client_db.read_bytes() == original_bytes
    assert archive.read_bytes() == original_bytes
    with closing(
        sqlite3.connect(archive.resolve().as_uri() + "?mode=ro", uri=True)
    ) as kept:
        change_id, record = kept.execute(
            "SELECT change_id,record_json FROM outbox"
        ).fetchone()
        assert change_id == recovery.queued["change_id"]
        assert json.loads(record) == recovery.queued["record"]
