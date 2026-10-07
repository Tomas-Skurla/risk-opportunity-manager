from __future__ import annotations

import sqlite3

import pytest
from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore
from riskapp_client.services.helpdesk_service import HelpDeskService


def test_outbox_squashes_changes_without_rebasing_an_unacknowledged_write(
    local_store,
) -> None:
    """A later local edit must retain the first write's server base version."""
    local_store.create_local_project(name="P", project_id="p1")
    local_store.upsert_local_risk(
        risk_id="r1",
        project_id="p1",
        title="R",
        probability=2,
        impact=2,
        version=0,
        dirty=1,
    )
    outbox = OutboxStore(local_store)
    outbox.queue_risk_upsert(
        "p1", {"id": "r1", "title": "R1", "probability": 3, "impact": 4}
    )
    assert outbox.pending_count("p1") == 1
    # Simulate a newer server version becoming visible locally before the
    # queued write has been acknowledged. The queued write must not silently
    # adopt that version or it could overwrite the intervening server edit.
    local_store.conn.execute("UPDATE risks SET version=2 WHERE id='r1';")
    local_store.conn.commit()
    outbox.queue_risk_upsert(
        "p1", {"id": "r1", "title": "R2", "probability": 4, "impact": 5}
    )
    # Still one pending change due to squash behavior.
    assert outbox.pending_count("p1") == 1
    changes = outbox.get_pending_changes("p1")
    assert len(changes) == 1
    assert changes[0]["entity"] == "risk"
    assert changes[0]["op"] == "upsert"
    assert changes[0]["base_version"] is None
    assert changes[0]["record"]["title"] == "R2"


def test_requeue_conflict_creates_new_change_id_and_updates_base_version(
    local_store,
) -> None:
    """Requeue a conflict with a new ID and the server's base version."""

    local_store.create_local_project(name="P", project_id="p1")
    local_store.upsert_local_risk(
        risk_id="r1",
        project_id="p1",
        title="R",
        probability=2,
        impact=2,
        version=1,
        dirty=1,
    )
    outbox = OutboxStore(local_store)
    outbox.queue_risk_upsert(
        "p1", {"id": "r1", "title": "R1", "probability": 2, "impact": 2}
    )
    pending = outbox.get_pending_changes("p1")
    old_id = pending[0]["change_id"]
    new_id = outbox.requeue_conflict_with_new_id(old_id, server_version=7)
    assert new_id is not None
    assert new_id != old_id
    changes = outbox.get_pending_changes("p1")
    assert len(changes) == 1
    assert changes[0]["change_id"] == new_id
    assert changes[0]["base_version"] == 7


def test_get_blocked_changes_exposes_conflict_reason_and_title(local_store) -> None:
    """Expose a blocked change's reason, version, and entity title."""

    local_store.create_local_project(name="P", project_id="p1")
    local_store.upsert_local_risk(
        risk_id="r1",
        project_id="p1",
        title="Server race",
        probability=2,
        impact=2,
        version=1,
        dirty=1,
    )
    outbox = OutboxStore(local_store)
    outbox.queue_risk_upsert(
        "p1", {"id": "r1", "title": "Server race", "probability": 2, "impact": 2}
    )
    pending = outbox.get_pending_changes("p1")
    change_id = pending[0]["change_id"]
    outbox.block_outbox_id(
        change_id,
        (
            f'{{"change_id": "{change_id}", "reason": "Server version changed", '
            '"server_version": 9}'
        ),
        failure_kind="conflict",
    )
    assert outbox.blocked_count("p1") == 1
    assert outbox.conflict_count("p1") == 1
    assert outbox.error_count("p1") == 0
    blocked = outbox.get_blocked_changes("p1")
    assert len(blocked) == 1
    assert blocked[0]["entity"] == "risk"
    assert blocked[0]["title"] == "Server race"
    assert blocked[0]["reason"] == "Server version changed"
    assert blocked[0]["server_version"] == 9
    assert blocked[0]["failure_kind"] == "conflict"


def test_complete_conflict_payload_survives_database_restart(tmp_path) -> None:
    """Conflict records are stored losslessly instead of in the 500-char summary."""

    db_file = tmp_path / "persistent-conflict.db"
    store = LocalStore(str(db_file))
    try:
        project = store.create_local_project(name="P", project_id="p1")
        store.upsert_local_risk(
            risk_id="r1",
            project_id=project.id,
            title="Local value",
            probability=5,
            impact=4,
            version=2,
        )
        outbox = OutboxStore(store)
        outbox.queue_risk_upsert(
            project.id,
            {"id": "r1", "title": "Local value", "probability": 5, "impact": 4},
        )
        change_id = outbox.get_pending_changes(project.id)[0]["change_id"]
        server_record = {
            "id": "r1",
            "project_id": project.id,
            "title": "Server value",
            "description": "full server description " * 80,
            "probability": 2,
            "impact": 3,
            "version": 7,
            "updated_at": "2026-09-04T12:00:00",
        }
        outbox.block_outbox_id(
            change_id,
            {
                "change_id": change_id,
                "status": "conflict",
                "reason": "version_mismatch",
                "server_version": 7,
                "server_record": server_record,
                "server_updated_at": "2026-09-04T12:00:00",
            },
            failure_kind="conflict",
        )
    finally:
        store.close()

    with LocalStore(str(db_file)) as reopened:
        blocked = OutboxStore(reopened).get_blocked_changes("p1")
        assert len(blocked) == 1
        assert blocked[0]["change_id"] == change_id
        assert blocked[0]["project_id"] == "p1"
        assert blocked[0]["server_version"] == 7
        assert blocked[0]["server_updated_at"] == "2026-09-04T12:00:00"
        assert blocked[0]["server_record"] == server_record
        assert len(blocked[0]["server_record"]["description"]) > 500


def test_helpdesk_outbox_uses_ticket_version_for_base_version(local_store) -> None:
    """Helpdesk outbox upsert records the ticket's local version as the base_version"""

    local_store.create_local_project(name="P", project_id="p1")
    ticket = local_store.create_helpdesk_ticket(
        "p1",
        title="CSV export broken",
        description="fails on open",
        category="bug",
        priority="high",
        reporter_email="qa@example.com",
    )
    local_store.conn.execute(
        "UPDATE helpdesk_tickets SET version=4, dirty=0 WHERE id=?;",
        (ticket.id,),
    )
    local_store.conn.commit()

    outbox = OutboxStore(local_store)
    outbox.queue_helpdesk_upsert(
        ticket.id,
        "p1",
        title="CSV export broken",
        description="fails on open",
        category="bug",
        priority="critical",
        status="open",
        reporter_email="qa@example.com",
    )

    changes = outbox.get_pending_changes("p1")
    assert len(changes) == 1
    assert changes[0]["entity"] == "helpdesk_ticket"
    assert changes[0]["base_version"] == 4
    assert changes[0]["record"]["priority"] == "critical"


def test_helpdesk_delete_unsynced_ticket_discards_pending_change(local_store) -> None:
    """Deleting an unsynced helpdesk ticket discards its pending outbox change"""

    local_store.create_local_project(name="P", project_id="p1")
    outbox = OutboxStore(local_store)
    service = HelpDeskService(local_store, outbox)

    ticket = service.create(
        "p1",
        title="Unsynced ticket",
        description="remove me before push",
        category="question",
        priority="low",
        reporter_email="qa@example.com",
    )
    assert outbox.pending_count("p1") == 1

    service.delete(ticket.id)

    assert outbox.pending_count("p1") == 0
    assert local_store.get_helpdesk_ticket_project_id(ticket.id) is None


def test_requeue_rolls_back_if_replacement_insert_fails(local_store) -> None:
    """A failed conflict requeue cannot delete the existing offline change."""

    project = local_store.create_local_project(name="P", project_id="p1")
    local_store.upsert_local_risk(
        risk_id="r1",
        project_id=project.id,
        title="Keep me",
        probability=2,
        impact=2,
    )
    outbox = OutboxStore(local_store)
    outbox.queue_risk_upsert(
        project.id,
        {"id": "r1", "title": "Keep me", "probability": 2, "impact": 2},
    )
    original = outbox.get_pending_changes(project.id)[0]
    local_store.conn.execute("""
        CREATE TRIGGER reject_outbox_insert
        BEFORE INSERT ON outbox
        BEGIN
            SELECT RAISE(ABORT, 'simulated insert failure');
        END;
        """)

    with pytest.raises(sqlite3.IntegrityError):
        outbox.requeue_conflict_with_new_id(original["change_id"], 7)

    remaining = outbox.get_pending_changes(project.id)
    assert [change["change_id"] for change in remaining] == [original["change_id"]]
