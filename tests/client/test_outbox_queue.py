from __future__ import annotations

import sqlite3

import pytest


def test_outbox_squashes_multiple_changes_for_same_entity_id(tmp_path) -> None:
    """Outbox squashes successive upserts for the same risk into a single pending change"""
    from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
    from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore

    db_file = tmp_path / "client_outbox.db"
    store = LocalStore(str(db_file))
    try:
        # Minimal project + risk row so the outbox can fetch (project_id, version).
        store.conn.execute(
            "INSERT INTO projects (id, name, description) VALUES (?,?,?);",
            ("p1", "P", ""),
        )
        store.upsert_local_risk(
            risk_id="r1",
            project_id="p1",
            title="R",
            probability=2,
            impact=2,
            version=0,
            dirty=1,
        )
        outbox = OutboxStore(store)
        outbox.queue_risk_upsert(
            "p1", {"id": "r1", "title": "R1", "probability": 3, "impact": 4}
        )
        assert outbox.pending_count("p1") == 1
        # Mark risk as already synced (version 2), then queue again.
        store.conn.execute("UPDATE risks SET version=2 WHERE id='r1';")
        store.conn.commit()
        outbox.queue_risk_upsert(
            "p1", {"id": "r1", "title": "R2", "probability": 4, "impact": 5}
        )
        # Still one pending change due to squash behavior.
        assert outbox.pending_count("p1") == 1
        changes = outbox.get_pending_changes("p1")
        assert len(changes) == 1
        assert changes[0]["entity"] == "risk"
        assert changes[0]["op"] == "upsert"
        assert changes[0]["base_version"] == 2
        assert changes[0]["record"]["title"] == "R2"
    finally:
        store.close()


def test_requeue_conflict_creates_new_change_id_and_updates_base_version(
    tmp_path,
) -> None:
    """Requeueing a conflicted change assigns a new change_id and the server's base_version"""
    from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
    from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore

    db_file = tmp_path / "client_outbox_conflict.db"
    store = LocalStore(str(db_file))
    try:
        store.conn.execute(
            "INSERT INTO projects (id, name, description) VALUES (?,?,?);",
            ("p1", "P", ""),
        )
        store.upsert_local_risk(
            risk_id="r1",
            project_id="p1",
            title="R",
            probability=2,
            impact=2,
            version=1,
            dirty=1,
        )
        outbox = OutboxStore(store)
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
    finally:
        store.close()


def test_get_blocked_changes_exposes_conflict_reason_and_title(tmp_path) -> None:
    """Blocked outbox entries expose the conflict reason, server_version, and entity title"""
    from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
    from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore

    db_file = tmp_path / "client_outbox_blocked.db"
    store = LocalStore(str(db_file))
    try:
        store.conn.execute(
            "INSERT INTO projects (id, name, description) VALUES (?,?,?);",
            ("p1", "P", ""),
        )
        store.upsert_local_risk(
            risk_id="r1",
            project_id="p1",
            title="Server race",
            probability=2,
            impact=2,
            version=1,
            dirty=1,
        )
        outbox = OutboxStore(store)
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
    finally:
        store.close()


def test_helpdesk_outbox_uses_ticket_version_for_base_version(tmp_path) -> None:
    """Helpdesk outbox upsert records the ticket's local version as the base_version"""
    from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
    from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore

    db_file = tmp_path / "client_helpdesk_outbox.db"
    store = LocalStore(str(db_file))
    try:
        store.conn.execute(
            "INSERT INTO projects (id, name, description) VALUES (?,?,?);",
            ("p1", "P", ""),
        )
        ticket = store.create_helpdesk_ticket(
            "p1",
            title="CSV export broken",
            description="fails on open",
            category="bug",
            priority="high",
            reporter_email="qa@example.com",
        )
        store.conn.execute(
            "UPDATE helpdesk_tickets SET version=4, dirty=0 WHERE id=?;",
            (ticket.id,),
        )
        store.conn.commit()

        outbox = OutboxStore(store)
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
    finally:
        store.close()


def test_helpdesk_delete_unsynced_ticket_discards_pending_change(tmp_path) -> None:
    """Deleting an unsynced helpdesk ticket discards its pending outbox change"""
    from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
    from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore
    from riskapp_client.services.helpdesk_service import HelpDeskService

    db_file = tmp_path / "client_helpdesk_delete.db"
    store = LocalStore(str(db_file))
    try:
        store.conn.execute(
            "INSERT INTO projects (id, name, description) VALUES (?,?,?);",
            ("p1", "P", ""),
        )
        outbox = OutboxStore(store)
        service = HelpDeskService(store, outbox)

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
        assert store.get_helpdesk_ticket_project_id(ticket.id) is None
    finally:
        store.close()


def test_requeue_rolls_back_if_replacement_insert_fails(tmp_path) -> None:
    """A failed conflict requeue cannot delete the existing offline change."""
    from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
    from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore

    store = LocalStore(str(tmp_path / "outbox_atomic.db"))
    try:
        project = store.create_local_project(name="P", project_id="p1")
        store.upsert_local_risk(
            risk_id="r1",
            project_id=project.id,
            title="Keep me",
            probability=2,
            impact=2,
        )
        outbox = OutboxStore(store)
        outbox.queue_risk_upsert(
            project.id,
            {"id": "r1", "title": "Keep me", "probability": 2, "impact": 2},
        )
        original = outbox.get_pending_changes(project.id)[0]
        store.conn.execute("""
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
    finally:
        store.close()
