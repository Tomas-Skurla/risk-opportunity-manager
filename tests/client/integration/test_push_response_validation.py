"""A malformed receipt must never acknowledge unrelated local work."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from riskapp_client.services.offline_first_facade import OfflineFirstBackend
from riskapp_client.services.synchronization_service import SyncService


@pytest.mark.parametrize(
    "malformation",
    [
        "foreign",
        "duplicate",
        "missing",
        "mixed",
        "entity",
        "entity_id",
        "record_id",
        "project_id",
        "status_list",
        "entity_list",
    ],
)
def test_invalid_receipt_preserves_both_projects(local_store, malformation):
    backend = OfflineFirstBackend(local_store)
    for project_id in ("project-a", "project-b"):
        local_store.create_local_project(name=project_id, project_id=project_id)
        backend.create_risk(project_id, title="Keep me", probability=2, impact=2)
    outbox = backend.outbox
    changes = outbox.get_pending_changes("project-a")
    other = outbox.get_pending_changes("project-b")
    result = {"change_id": changes[0]["change_id"], "status": "accepted"}
    results = [result]
    if malformation == "foreign":
        result["change_id"] = other[0]["change_id"]
    elif malformation == "duplicate":
        results.append(dict(result))
    elif malformation == "missing":
        results = []
    elif malformation == "mixed":
        results.append({"change_id": other[0]["change_id"], "status": "accepted"})
    elif malformation in ("entity", "entity_id"):
        result[malformation] = "wrong"
    elif malformation in ("record_id", "project_id"):
        result["server_record"] = {
            "id" if malformation == "record_id" else "project_id": "wrong"
        }
    elif malformation == "status_list":
        result["status"] = []
    else:
        result["entity"] = []
    remote = Mock()
    remote.sync_push.return_value = {"results": results}
    summary = SyncService(local_store, outbox, remote).sync_project("project-a")
    assert summary["state"] == "retry_wait"
    assert summary["pushed"] == 0
    assert outbox.get_pending_changes("project-b") == other
    assert outbox.pending_count("project-a") == 1
    assert local_store.get_risk_row(changes[0]["record"]["id"])["dirty"] == 1
    remote.sync_pull.assert_not_called()
