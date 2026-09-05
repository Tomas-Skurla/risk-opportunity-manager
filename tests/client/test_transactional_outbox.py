"""Failure-injection tests for the strict local transactional outbox."""

from __future__ import annotations

import sqlite3

import pytest
from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
from riskapp_client.services.offline_first_facade import OfflineFirstBackend


def _backend(tmp_path) -> tuple[LocalStore, OfflineFirstBackend, str]:
    store = LocalStore(str(tmp_path / "transactional-outbox.db"))
    project = store.create_local_project(name="Project", project_id="project-1")
    store.set_meta("user_id", "user-1")
    return store, OfflineFirstBackend(store), project.id


def _reject_outbox_inserts(store: LocalStore) -> None:
    store.conn.execute(
        """
        CREATE TRIGGER reject_outbox_insert
        BEFORE INSERT ON outbox
        BEGIN
            SELECT RAISE(ABORT, 'simulated outbox failure');
        END;
        """
    )
    store.conn.commit()


@pytest.mark.parametrize("kind", ["risk", "opportunity"])
def test_scored_update_rolls_back_with_failed_outbox_replacement(
    tmp_path, kind: str
) -> None:
    store, backend, project_id = _backend(tmp_path)
    try:
        if kind == "risk":
            entity = backend.create_risk(
                project_id, title="Original", probability=2, impact=3
            )
            get_row = store.get_risk_row
            update = backend.update_risk
        else:
            entity = backend.create_opportunity(
                project_id, title="Original", probability=2, impact=3
            )
            get_row = store.get_opportunity_row
            update = backend.update_opportunity

        original_change = backend.outbox.get_pending_changes(project_id)[0]
        _reject_outbox_inserts(store)

        with pytest.raises(sqlite3.IntegrityError, match="simulated outbox failure"):
            update(
                project_id,
                entity.id,
                title="Must roll back",
                probability=5,
                impact=5,
            )

        assert get_row(entity.id)["title"] == "Original"
        remaining = backend.outbox.get_pending_changes(project_id)
        assert remaining == [original_change]
    finally:
        store.close()


def test_action_create_rolls_back_when_outbox_insert_fails(tmp_path) -> None:
    store, backend, project_id = _backend(tmp_path)
    try:
        risk = backend.create_risk(
            project_id, title="Parent", probability=2, impact=2
        )
        _reject_outbox_inserts(store)

        with pytest.raises(sqlite3.IntegrityError, match="simulated outbox failure"):
            backend.create_action(
                project_id,
                target_type="risk",
                target_id=risk.id,
                kind="mitigation",
                title="Must roll back",
                description="",
                status="open",
                owner_user_id=None,
            )

        assert store.list_actions(project_id) == []
    finally:
        store.close()


def test_assessment_create_rolls_back_when_outbox_insert_fails(tmp_path) -> None:
    store, backend, project_id = _backend(tmp_path)
    try:
        risk = backend.create_risk(
            project_id, title="Parent", probability=2, impact=2
        )
        _reject_outbox_inserts(store)

        with pytest.raises(sqlite3.IntegrityError, match="simulated outbox failure"):
            backend.upsert_my_assessment(
                project_id, "risk", risk.id, probability=4, impact=3
            )

        assert store.list_assessments(project_id, "risk", risk.id) == []
    finally:
        store.close()


def test_helpdesk_create_rolls_back_when_outbox_insert_fails(tmp_path) -> None:
    store, backend, project_id = _backend(tmp_path)
    try:
        _reject_outbox_inserts(store)

        with pytest.raises(sqlite3.IntegrityError, match="simulated outbox failure"):
            backend.create_helpdesk_ticket(project_id, title="Must roll back")

        assert store.list_helpdesk_tickets(project_id) == []
    finally:
        store.close()


def test_helpdesk_delete_rolls_back_and_preserves_previous_change(tmp_path) -> None:
    store, backend, project_id = _backend(tmp_path)
    try:
        ticket = backend.create_helpdesk_ticket(project_id, title="Keep me")
        store.conn.execute(
            "UPDATE helpdesk_tickets SET version=3, dirty=0 WHERE id=?;",
            (ticket.id,),
        )
        store.conn.commit()
        backend.update_helpdesk_ticket(ticket.id, title="Queued update")
        original_change = backend.outbox.get_pending_changes(project_id)[0]
        _reject_outbox_inserts(store)

        with pytest.raises(sqlite3.IntegrityError, match="simulated outbox failure"):
            backend.delete_helpdesk_ticket(ticket.id)

        remaining_ticket = store.list_helpdesk_tickets(project_id)[0]
        assert remaining_ticket.title == "Queued update"
        assert remaining_ticket.is_deleted is False
        assert backend.outbox.get_pending_changes(project_id) == [original_change]
    finally:
        store.close()


def test_caught_nested_write_still_rolls_back_outer_transaction(tmp_path) -> None:
    store = LocalStore(str(tmp_path / "rollback-only.db"))
    try:
        with (
            pytest.raises(RuntimeError, match="transaction rolled back"),
            store.write_transaction(),
        ):
            store.create_local_project(name="Outer", project_id="outer")
            try:
                with store.write_transaction():
                    store.create_local_project(name="Inner", project_id="inner")
                    raise ValueError("nested failure")
            except ValueError:
                pass

        assert store.get_project("outer") is None
        assert store.get_project("inner") is None
    finally:
        store.close()
