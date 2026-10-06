"""Server codes win on pull: colliding cached codes are released, local work kept."""

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


@pytest.mark.parametrize("one_page", [True, False], ids=["one-page", "two-pages"])
def test_pull_applies_codes_swapped_on_the_server(tmp_path, one_page) -> None:
    """A code moved to another record frees it; the record's own update follows."""
    with LocalStore(str(tmp_path / "swap.db")) as store:
        project = store.create_local_project(name="Project", project_id="project-1")
        store.apply_pull_risks(
            project.id,
            [
                {"id": "a", "code": "R-001", "version": 1},
                {"id": "b", "code": "R-002", "version": 1},
            ],
        )
        # The server applied a -> R-999, b -> R-001, a -> R-002, so a pull
        # delivers b before a, possibly on separate pages.
        b_update = {"id": "b", "code": "R-001", "version": 2}
        a_update = {"id": "a", "code": "R-002", "version": 3}
        if one_page:
            store.apply_pull_risks(project.id, [b_update, a_update])
        else:
            store.apply_pull_risks(project.id, [b_update])
            released = store.get_risk_row("a")
            assert released is not None and released["code"] is None
            store.apply_pull_risks(project.id, [a_update])

        a, b = store.get_risk_row("a"), store.get_risk_row("b")
        assert a is not None and (a["code"], a["version"]) == ("R-002", 3)
        assert b is not None and (b["code"], b["version"]) == ("R-001", 2)
