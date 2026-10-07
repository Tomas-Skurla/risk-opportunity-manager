"""Failure-injection tests for the strict local transactional outbox."""

from __future__ import annotations

import sqlite3

import pytest
from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
from riskapp_client.services.offline_first_facade import OfflineFirstBackend


def _backend(local_store: LocalStore) -> tuple[OfflineFirstBackend, str]:
    project = local_store.create_local_project(name="Project", project_id="project-1")
    local_store.set_meta("user_id", "user-1")
    return OfflineFirstBackend(local_store), project.id


def _reject_outbox_inserts(store: LocalStore) -> None:
    store.conn.execute("""
        CREATE TRIGGER reject_outbox_insert
        BEFORE INSERT ON outbox
        BEGIN
            SELECT RAISE(ABORT, 'simulated outbox failure');
        END;
        """)
    store.conn.commit()


@pytest.mark.parametrize("kind", ["risk", "opportunity"])
def test_scored_update_rolls_back_with_failed_outbox_replacement(
    local_store, kind: str
) -> None:

    backend, project_id = _backend(local_store)
    if kind == "risk":
        entity = backend.create_risk(
            project_id, title="Original", probability=2, impact=3
        )

        get_row = local_store.get_risk_row
        update = backend.update_risk
    else:
        entity = backend.create_opportunity(
            project_id, title="Original", probability=2, impact=3
        )
        get_row = local_store.get_opportunity_row
        update = backend.update_opportunity

    original_change = backend.outbox.get_pending_changes(project_id)[0]
    _reject_outbox_inserts(local_store)

    with pytest.raises(sqlite3.IntegrityError, match="simulated outbox failure"):
        update(
            project_id,
            entity.id,
            title="Must roll back",
            probability=5,
            impact=5,
        )

    row = get_row(entity.id)
    assert row is not None
    assert row["title"] == "Original"
    remaining = backend.outbox.get_pending_changes(project_id)
    assert remaining == [original_change]


def test_action_create_rolls_back_when_outbox_insert_fails(local_store) -> None:
    backend, project_id = _backend(local_store)
    risk = backend.create_risk(project_id, title="Parent", probability=2, impact=2)
    _reject_outbox_inserts(local_store)

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

    assert local_store.list_actions(project_id) == []


def test_assessment_create_rolls_back_when_outbox_insert_fails(local_store) -> None:
    backend, project_id = _backend(local_store)
    risk = backend.create_risk(project_id, title="Parent", probability=2, impact=2)
    _reject_outbox_inserts(local_store)

    with pytest.raises(sqlite3.IntegrityError, match="simulated outbox failure"):
        backend.upsert_my_assessment(
            project_id, "risk", risk.id, probability=4, impact=3
        )

    assert local_store.list_assessments(project_id, "risk", risk.id) == []


def test_helpdesk_create_rolls_back_when_outbox_insert_fails(local_store) -> None:
    backend, project_id = _backend(local_store)
    _reject_outbox_inserts(local_store)

    with pytest.raises(sqlite3.IntegrityError, match="simulated outbox failure"):
        backend.create_helpdesk_ticket(project_id, title="Must roll back")

    assert local_store.list_helpdesk_tickets(project_id) == []


@pytest.mark.parametrize("version", [0, 3])
def test_helpdesk_delete_rolls_back_and_preserves_previous_change(
    local_store, version: int
) -> None:
    backend, project_id = _backend(local_store)
    ticket = backend.create_helpdesk_ticket(project_id, title="Keep me")
    local_store.conn.execute(
        "UPDATE helpdesk_tickets SET version=?, dirty=0 WHERE id=?;",
        (version, ticket.id),
    )
    local_store.conn.commit()
    backend.update_helpdesk_ticket(ticket.id, title="Queued update")
    original_change = backend.outbox.get_pending_changes(project_id)[0]
    if version == 0:
        backend.outbox.mark_outbox_ids_attempted([original_change["change_id"]])
    _reject_outbox_inserts(local_store)

    with pytest.raises(sqlite3.IntegrityError, match="simulated outbox failure"):
        backend.delete_helpdesk_ticket(ticket.id)

    remaining_ticket = local_store.list_helpdesk_tickets(project_id)[0]
    assert remaining_ticket.title == "Queued update"
    assert remaining_ticket.is_deleted is False
    assert backend.outbox.get_pending_changes(project_id) == [original_change]


def test_caught_nested_write_still_rolls_back_outer_transaction(local_store) -> None:
    with (
        pytest.raises(RuntimeError, match="transaction rolled back"),
        local_store.write_transaction(),
    ):
        local_store.create_local_project(name="Outer", project_id="outer")
        try:
            with local_store.write_transaction():
                local_store.create_local_project(name="Inner", project_id="inner")
                raise ValueError("nested failure")
        except ValueError:
            pass

    assert local_store.get_project("outer") is None
    assert local_store.get_project("inner") is None
