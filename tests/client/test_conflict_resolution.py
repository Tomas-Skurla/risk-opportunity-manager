"""Conflict Center resolution behavior against the persistent local store."""

from __future__ import annotations

import json
import sqlite3

import pytest
from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore
from riskapp_client.services.synchronization_service import SyncService


def _risk_conflict(
    tmp_path,
    *,
    local_version: int = 3,
    server_version: int = 5,
) -> tuple[LocalStore, OutboxStore, SyncService, str]:
    store = LocalStore(str(tmp_path / "conflicts.db"))
    store.create_local_project(name="Project", project_id="project-1")
    store.upsert_local_risk(
        risk_id="risk-1",
        project_id="project-1",
        title="Local title",
        probability=5,
        impact=4,
        version=local_version,
        updated_at="2026-09-04T10:00:00",
    )
    outbox = OutboxStore(store)
    outbox.queue_risk_upsert(
        "project-1",
        {
            "id": "risk-1",
            "title": "Local title",
            "probability": 5,
            "impact": 4,
        },
    )
    change_id = outbox.get_pending_changes("project-1")[0]["change_id"]
    outbox.block_outbox_id(
        change_id,
        {
            "change_id": change_id,
            "status": "conflict",
            "reason": "version_mismatch",
            "failure_kind": "conflict",
            "retryable": False,
            "server_version": server_version,
            "server_updated_at": "2026-09-04T12:00:00",
            "server_record": {
                "id": "risk-1",
                "project_id": "project-1",
                "type": "risk",
                "title": "Server title",
                "description": "Server description",
                "probability": 2,
                "impact": 3,
                "status": "concept",
                "version": server_version,
                "is_deleted": False,
                "updated_at": "2026-09-04T12:00:00",
            },
        },
        failure_kind="conflict",
    )
    return store, outbox, SyncService(store, outbox, None), change_id


def test_keep_mine_requeues_with_fresh_id_and_newest_known_version(tmp_path) -> None:
    store, outbox, service, old_change_id = _risk_conflict(
        tmp_path, local_version=6, server_version=5
    )
    try:
        result = service.resolve_conflict(old_change_id, "keep_mine")

        assert result["resolved"] is True
        assert result["base_version"] == 6
        assert result["replacement_change_id"] != old_change_id
        assert outbox.get_blocked_change(old_change_id) is None
        pending = outbox.get_pending_changes("project-1")
        assert len(pending) == 1
        assert pending[0]["change_id"] == result["replacement_change_id"]
        assert pending[0]["base_version"] == 6
        assert pending[0]["record"]["title"] == "Local title"
        assert store.get_risk_row("risk-1")["title"] == "Local title"
    finally:
        store.close()


def test_use_server_atomically_replaces_local_copy_and_rewinds_watermark(
    tmp_path,
) -> None:
    store, outbox, service, change_id = _risk_conflict(tmp_path)
    try:
        store.set_last_server_time("project-1", "2026-09-04T13:00:00")

        result = service.resolve_conflict(change_id, "use_server")

        assert result == {
            "change_id": change_id,
            "resolution": "use_server",
            "resolved": True,
            "project_id": "project-1",
        }
        assert outbox.get_blocked_change(change_id) is None
        assert outbox.pending_count("project-1") == 0
        row = store.get_risk_row("risk-1")
        assert row["title"] == "Server title"
        assert row["description"] == "Server description"
        assert row["probability"] == 2
        assert row["impact"] == 3
        assert row["version"] == 5
        assert row["dirty"] == 0
        assert store.get_last_server_time("project-1") == "1970-01-01T00:00:00"
    finally:
        store.close()


def test_later_leaves_conflict_and_local_copy_untouched(tmp_path) -> None:
    store, outbox, service, change_id = _risk_conflict(tmp_path)
    try:
        before = dict(store.get_risk_row("risk-1"))

        result = service.resolve_conflict(change_id, "later")

        assert result["resolved"] is False
        assert result["resolution"] == "later"
        assert outbox.get_blocked_change(change_id) is not None
        assert dict(store.get_risk_row("risk-1")) == before
    finally:
        store.close()


def test_use_server_validation_failure_preserves_conflict_and_local_copy(
    tmp_path,
) -> None:
    store, outbox, service, change_id = _risk_conflict(tmp_path)
    try:
        result_row = store.conn.execute(
            "SELECT result_json FROM outbox WHERE change_id=?;", (change_id,)
        ).fetchone()
        outcome = json.loads(result_row["result_json"])
        outcome["server_record"]["project_id"] = "another-project"
        store.conn.execute(
            "UPDATE outbox SET result_json=? WHERE change_id=?;",
            (json.dumps(outcome), change_id),
        )
        store.conn.commit()
        before = dict(store.get_risk_row("risk-1"))

        with pytest.raises(RuntimeError, match="another project"):
            service.resolve_conflict(change_id, "use_server")

        assert outbox.get_blocked_change(change_id) is not None
        assert dict(store.get_risk_row("risk-1")) == before
    finally:
        store.close()


def test_use_server_rolls_back_outbox_delete_when_local_apply_fails(tmp_path) -> None:
    store, outbox, service, change_id = _risk_conflict(tmp_path)
    try:
        before = dict(store.get_risk_row("risk-1"))
        store.conn.execute("""
            CREATE TRIGGER reject_conflict_resolution
            BEFORE UPDATE ON risks
            BEGIN
                SELECT RAISE(ABORT, 'simulated local apply failure');
            END;
            """)
        store.conn.commit()

        with pytest.raises(sqlite3.IntegrityError, match="simulated local apply"):
            service.resolve_conflict(change_id, "use_server")

        assert outbox.get_blocked_change(change_id) is not None
        assert dict(store.get_risk_row("risk-1")) == before
    finally:
        store.close()


def test_use_server_normalizes_legacy_ambiguous_action_parent(tmp_path) -> None:
    store = LocalStore(str(tmp_path / "action-conflict.db"))
    try:
        store.create_local_project(name="Project", project_id="project-1")
        store.upsert_local_risk(
            risk_id="risk-1",
            project_id="project-1",
            title="Parent",
            probability=2,
            impact=2,
            version=1,
        )
        store.upsert_local_action(
            action_id="action-1",
            project_id="project-1",
            risk_id="risk-1",
            opportunity_id=None,
            kind="mitigation",
            title="Local action",
            description="",
            status="open",
            owner_user_id=None,
            version=2,
        )
        outbox = OutboxStore(store)
        outbox.queue_action_upsert(
            "action-1",
            "project-1",
            risk_id="risk-1",
            opportunity_id=None,
            kind="mitigation",
            title="Local action",
            description="",
            status="open",
            owner_user_id=None,
        )
        change_id = outbox.get_pending_changes("project-1")[0]["change_id"]
        outbox.block_outbox_id(
            change_id,
            {
                "reason": "version_mismatch",
                "server_version": 3,
                "server_record": {
                    "id": "action-1",
                    "project_id": "project-1",
                    "item_id": "risk-1",
                    # Patch 8 payloads used to contain both aliases.
                    "risk_id": "risk-1",
                    "opportunity_id": "risk-1",
                    "kind": "mitigation",
                    "title": "Server action",
                    "description": "",
                    "status": "done",
                    "owner_user_id": None,
                    "version": 3,
                    "is_deleted": False,
                    "updated_at": "2026-09-04T12:00:00",
                },
            },
            failure_kind="conflict",
        )

        SyncService(store, outbox, None).resolve_conflict(change_id, "use_server")

        row = store.conn.execute(
            "SELECT * FROM actions WHERE id='action-1';"
        ).fetchone()
        assert row["title"] == "Server action"
        assert row["risk_id"] == "risk-1"
        assert row["opportunity_id"] is None
        assert row["version"] == 3
        assert row["dirty"] == 0
    finally:
        store.close()


def test_conflict_details_excludes_other_blocked_failures(tmp_path) -> None:
    store, outbox, service, change_id = _risk_conflict(tmp_path)
    try:
        store.upsert_local_opportunity(
            opportunity_id="opportunity-1",
            project_id="project-1",
            title="Opportunity",
            probability=2,
            impact=3,
            version=1,
        )
        outbox.queue_opportunity_upsert(
            "project-1",
            {
                "id": "opportunity-1",
                "title": "Opportunity",
                "probability": 2,
                "impact": 3,
            },
        )
        validation_id = outbox.get_pending_changes("project-1")[0]["change_id"]
        outbox.block_outbox_id(
            validation_id,
            {"reason": "invalid_record"},
            failure_kind="validation",
        )

        details = service.conflict_details("project-1")

        assert [item["change_id"] for item in details] == [change_id]
        assert details[0]["server_record"]["title"] == "Server title"
    finally:
        store.close()


@pytest.mark.parametrize("resolution", ["", "merge", "discard_everything"])
def test_unknown_conflict_resolution_is_rejected(tmp_path, resolution) -> None:
    store, outbox, service, change_id = _risk_conflict(tmp_path)
    try:
        with pytest.raises(ValueError, match="resolution must be"):
            service.resolve_conflict(change_id, resolution)
        assert outbox.get_blocked_change(change_id) is not None
    finally:
        store.close()
