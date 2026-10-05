"""Pulls must preserve blocked offline creates when server codes collide."""

import sqlite3
from unittest.mock import Mock

import pytest
from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
from riskapp_client.services.offline_first_facade import OfflineFirstBackend
from riskapp_client.services.synchronization_service import SyncService


@pytest.mark.parametrize("kind,prefix", [("risk", "R"), ("opportunity", "O")])
def test_blocked_offline_create_does_not_prevent_repeated_pulls(
    tmp_path, kind, prefix
) -> None:
    with LocalStore(str(tmp_path / "blocked-create.db")) as store:
        project = store.create_local_project(name="Project", project_id="project-1")
        backend = OfflineFirstBackend(store)
        local = getattr(backend, f"create_{kind}")(
            project.id, title="Offline work", probability=2, impact=3
        )
        change = backend.outbox.get_pending_changes(project.id)[0]
        remote = Mock()
        remote.sync_push.return_value = {
            "results": [
                {
                    "change_id": change["change_id"],
                    "status": "error",
                    "reason": "role_forbidden",
                    "detail": "Viewer cannot write",
                    "http_status": 403,
                    "failure_kind": "permission",
                    "retryable": False,
                }
            ]
        }
        incoming = {
            "id": "server-record",
            "project_id": project.id,
            "title": "Another device's record",
            "code": f"{prefix}-001",
            "probability": 4,
            "impact": 5,
            "version": 1,
        }
        payload = {
            "server_time": "2026-09-30T00:00:00",
            "server_sequence": 1,
            "risks": [],
            "opportunities": [],
            "actions": [],
            "assessments": [],
            "helpdesk_tickets": [],
        }
        payload["risks" if kind == "risk" else "opportunities"] = [incoming]
        remote.sync_pull.return_value = payload
        sync = SyncService(store, backend.outbox, remote)

        assert sync.sync_project(project.id)["state"] == "attention_required"
        blocked = store.conn.execute(
            "SELECT * FROM outbox WHERE change_id=?", (change["change_id"],)
        ).fetchone()
        assert blocked is not None and blocked["status"] == "blocked"
        blocked_before = dict(blocked)
        assert sync.sync_project(project.id)["state"] == "attention_required"
        remote.sync_push.assert_called_once()

        get_row = getattr(store, f"get_{kind}_row")
        provisional = get_row(local.id)
        authoritative = get_row(incoming["id"])
        assert provisional["title"] == "Offline work"
        assert provisional["version"] == 0
        assert provisional["dirty"] == 1
        assert provisional["code"] is None
        assert authoritative["code"] == f"{prefix}-001"
        assert (
            dict(
                store.conn.execute(
                    "SELECT * FROM outbox WHERE change_id=?", (change["change_id"],)
                ).fetchone()
            )
            == blocked_before
        )


def test_failed_pull_rolls_back_provisional_code_release(tmp_path) -> None:
    with LocalStore(str(tmp_path / "rollback.db")) as store:
        project = store.create_local_project(name="Project", project_id="project-1")
        backend = OfflineFirstBackend(store)
        local = backend.create_risk(
            project.id, title="Keep this", probability=2, impact=2
        )
        before = backend.outbox.get_pending_changes(project.id)
        incoming = {
            "id": "remote-risk",
            "title": "Remote",
            "code": "R-001",
            "version": 1,
        }
        invalid = {"id": "invalid", "version": "invalid"}

        with pytest.raises(ValueError):
            store.apply_pull_risks(project.id, [incoming, invalid])

        restored = store.get_risk_row(local.id)
        assert restored is not None
        assert restored["code"] == "R-001"
        assert store.get_risk_row(incoming["id"]) is None
        assert backend.outbox.get_pending_changes(project.id) == before


def test_pull_does_not_clear_an_acknowledged_records_code(tmp_path) -> None:
    with LocalStore(str(tmp_path / "canonical.db")) as store:
        project = store.create_local_project(name="Project", project_id="project-1")
        store.apply_pull_risks(
            project.id,
            [
                {
                    "id": "acknowledged",
                    "code": "R-001",
                    "version": 1,
                }
            ],
        )
        with pytest.raises(sqlite3.IntegrityError):
            store.apply_pull_risks(
                project.id,
                [
                    {
                        "id": "different",
                        "code": "R-001",
                        "version": 1,
                    }
                ],
            )
        acknowledged = store.get_risk_row("acknowledged")
        assert acknowledged is not None
        assert acknowledged["code"] == "R-001"
