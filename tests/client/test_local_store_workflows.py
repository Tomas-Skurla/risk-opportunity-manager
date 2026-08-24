"""Behavior tests for the SQLite-backed offline store."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore
from riskapp_client.domain.domain_models import Project


@pytest.fixture
def store(tmp_path) -> Iterator[LocalStore]:
    with LocalStore(str(tmp_path / "local-store.db")) as local_store:
        yield local_store


def test_sync_projects_preserves_local_and_nonempty_projects(store: LocalStore) -> None:
    store.create_local_project(name="Offline", project_id="local-offline")
    store.create_local_project(name="Active", project_id="server-active")
    store.create_local_project(name="Keep data", project_id="server-with-data")
    store.create_local_project(name="Remove empty", project_id="server-empty")
    store.set_last_server_time("server-empty", "2025-01-01T00:00:00")
    store.upsert_local_risk(
        risk_id="risk-local",
        project_id="server-with-data",
        title="Unsynced risk",
        probability=2,
        impact=3,
    )

    store.sync_projects(
        [
            Project("server-active", "Renamed by server"),
            Project("server-new", "New server project"),
        ]
    )

    projects = {project.id: project for project in store.list_projects()}
    assert set(projects) == {
        "local-offline",
        "server-active",
        "server-with-data",
        "server-new",
    }
    assert projects["server-active"].name == "Renamed by server"
    assert store.get_last_server_time("server-empty") == "1970-01-01T00:00:00"


def test_project_id_migration_is_atomic_and_idempotent(store: LocalStore) -> None:
    old_id = "local-project"
    new_id = "server-project"
    store.create_local_project(name="Promote", project_id=old_id)
    store.upsert_local_risk(
        risk_id="risk-1",
        project_id=old_id,
        title="Move me",
        probability=2,
        impact=4,
        version=2,
    )
    store.set_last_server_time(old_id, "2025-02-01T00:00:00")
    ticket = store.create_helpdesk_ticket(old_id, title="Move ticket")
    OutboxStore(store).queue_risk_upsert(
        old_id,
        {"id": "risk-1", "title": "Move me", "probability": 2, "impact": 4},
    )
    store.set_meta("bootstrap_project_id", old_id)
    store.set_meta("bootstrap_user_project_id", "another-project")
    store.set_meta("bootstrap_anon_project_id", old_id)

    store.migrate_project_id(old_project_id="", new_project_id=new_id)
    store.migrate_project_id(old_project_id=old_id, new_project_id="")
    store.migrate_project_id(old_project_id=old_id, new_project_id=old_id)
    store.migrate_project_id(old_project_id="missing", new_project_id=new_id)
    store.migrate_project_id(old_project_id=old_id, new_project_id=new_id)

    assert store.get_project(old_id) is None
    assert store.get_project(new_id) is not None
    assert store.get_risk_project_and_version("risk-1") == (new_id, 2)
    assert store.get_helpdesk_ticket_project_id(ticket.id) == new_id
    assert store.get_last_server_time(new_id) == "2025-02-01T00:00:00"
    assert OutboxStore(store).pending_count(new_id) == 1
    assert store.get_meta("bootstrap_project_id") == new_id
    assert store.get_meta("bootstrap_user_project_id") == "another-project"
    assert store.get_meta("bootstrap_anon_project_id") == new_id


def test_scored_entity_lifecycle_and_pull_conflict_preservation(
    store: LocalStore,
) -> None:
    project = store.create_local_project(name="Scored", project_id="project-1")
    assert store.next_risk_code(project.id) == "R-001"

    store.upsert_local_risk(
        risk_id="risk-1",
        project_id=project.id,
        title="Local title",
        probability=3,
        impact=2,
        impact_cost=5,
        code=" R-009 ",
        category=" Finance ",
        status=" ",
        version=2,
        updated_at="2025-01-01T00:00:00",
    )
    store.upsert_local_risk(
        risk_id="risk-nonnumeric",
        project_id=project.id,
        title="Non-numeric code",
        probability=1,
        impact=1,
        code="R-ALPHA",
    )
    assert store.next_risk_code(project.id) == "R-010"

    risk = next(item for item in store.list_risks(project.id) if item.id == "risk-1")
    assert risk.code == "R-009"
    assert risk.category == "Finance"
    assert risk.status == "concept"
    assert risk.impact == 5

    store.upsert_local_risk(
        risk_id="risk-1",
        project_id=project.id,
        title="Local edit",
        probability=4,
        impact=3,
        code="R-009",
        version=None,
        is_deleted=None,
        updated_at=None,
    )
    assert store.get_risk_project_and_version("risk-1") == (project.id, 2)

    with pytest.raises(KeyError, match="risk not found"):
        store.soft_delete_risk("missing")
    with pytest.raises(KeyError, match="opportunity not found"):
        store.get_opportunity_project_and_version("missing")

    outbox = OutboxStore(store)
    outbox.queue_risk_upsert(
        project.id,
        {"id": "risk-1", "title": "Local edit", "probability": 4, "impact": 3},
    )
    store.apply_pull_risks(
        project.id,
        [
            {
                "id": "risk-1",
                "title": "Server title must not win",
                "probability": 1,
                "impact": 1,
                "version": 7,
                "updated_at": "2025-02-01T00:00:00",
            },
            {
                "id": "risk-server",
                "title": "Server risk",
                "probability": 2,
                "impact": 2,
                "category": " Operations ",
                "status": "",
                "version": 1,
                "is_deleted": False,
            },
            {
                "id": "risk-deleted",
                "title": "Deleted remotely",
                "probability": 1,
                "impact": 1,
                "version": 4,
                "is_deleted": True,
            },
        ],
    )
    store.apply_pull_opportunities(
        project.id,
        [
            {
                "id": "opportunity-server",
                "title": "Server opportunity",
                "probability": 3,
                "impact": 4,
                "version": 1,
            }
        ],
    )

    pulled = {item.id: item for item in store.list_risks(project.id)}
    assert pulled["risk-1"].title == "Local edit"
    assert store.get_risk_project_and_version("risk-1") == (project.id, 7)
    assert pulled["risk-server"].category == "Operations"
    assert "risk-deleted" not in pulled
    assert store.list_opportunities(project.id)[0].id == "opportunity-server"

    assert store.soft_delete_risk("risk-nonnumeric")[0] == project.id
    assert "risk-nonnumeric" not in {item.id for item in store.list_risks(project.id)}


def test_action_and_assessment_pulls_cover_both_parent_types(store: LocalStore) -> None:
    project = store.create_local_project(name="Parents", project_id="project-1")
    store.upsert_local_risk(
        risk_id="risk-1",
        project_id=project.id,
        title="Risk",
        probability=2,
        impact=3,
    )
    store.upsert_local_opportunity(
        opportunity_id="opportunity-1",
        project_id=project.id,
        title="Opportunity",
        probability=4,
        impact=2,
    )

    with pytest.raises(KeyError, match="action not found"):
        store.get_action_project_and_version("missing")
    store.upsert_local_action(
        action_id="action-local",
        project_id=project.id,
        risk_id="risk-1",
        opportunity_id=None,
        kind="mitigation",
        title="Local action",
        description="",
        status="open",
        owner_user_id=None,
        version=2,
        updated_at="2025-01-01T00:00:00",
    )
    store.upsert_local_action(
        action_id="action-local",
        project_id=project.id,
        risk_id="risk-1",
        opportunity_id=None,
        kind="mitigation",
        title="Local action edited",
        description="",
        status="open",
        owner_user_id=None,
        version=None,
        is_deleted=None,
        updated_at=None,
    )
    outbox = OutboxStore(store)
    outbox.queue_action_upsert(
        "action-local",
        project.id,
        risk_id="risk-1",
        opportunity_id=None,
        kind="mitigation",
        title="Local action edited",
        status="open",
    )
    store.apply_pull_actions(
        project.id,
        [
            {
                "id": "action-local",
                "project_id": project.id,
                "risk_id": "risk-1",
                "kind": "mitigation",
                "title": "Server action",
                "version": 8,
            },
            {
                "id": "action-server",
                "project_id": project.id,
                "opportunity_id": "opportunity-1",
                "kind": "exploit",
                "title": "Exploit it",
                "status": "done",
                "version": 1,
            },
        ],
    )
    actions = {action.id: action for action in store.list_actions(project.id)}
    assert actions["action-local"].title == "Local action edited"
    assert actions["action-local"].version == 8
    assert actions["action-server"].opportunity_id == "opportunity-1"

    with pytest.raises(KeyError, match="assessment not found"):
        store.get_assessment_project_and_version("missing")
    store.upsert_local_assessment(
        assessment_id="assessment-pending",
        project_id=project.id,
        item_type="risk",
        item_id="risk-1",
        assessor_user_id="user-1",
        probability=2,
        impact=2,
        notes="Local notes",
        version=2,
        is_deleted=False,
        updated_at="2025-01-01T00:00:00",
        dirty=1,
    )
    outbox.queue_assessment_upsert(
        "assessment-pending",
        project.id,
        item_id="risk-1",
        risk_id="risk-1",
        probability=2,
        impact=2,
    )
    base = {
        "assessor_user_id": "user-server",
        "probability": 3,
        "impact": 4,
        "version": 1,
    }
    store.apply_pull_assessments(
        project.id,
        [
            {
                **base,
                "id": "assessment-pending",
                "item_id": "risk-1",
                "risk_id": "risk-1",
                "notes": "Server notes",
                "version": 9,
            },
            {
                **base,
                "id": "assessment-explicit-opportunity",
                "item_id": "opportunity-1",
                "opportunity_id": "opportunity-1",
            },
            {
                **base,
                "id": "assessment-explicit-risk",
                "item_id": "risk-1",
                "risk_id": "risk-1",
            },
            {
                **base,
                "id": "assessment-inferred-opportunity",
                "item_id": "opportunity-1",
            },
            {**base, "id": "assessment-inferred-risk", "item_id": "risk-1"},
            {**base, "id": "assessment-fallback-risk", "item_id": "unknown"},
        ],
    )

    pending = store.list_assessments(project.id, "risk", "risk-1")
    assert next(a for a in pending if a.id == "assessment-pending").notes == (
        "Local notes"
    )
    assert store.get_assessment_project_and_version("assessment-pending") == (
        project.id,
        9,
    )
    opportunity_ids = {
        assessment.id
        for assessment in store.list_assessments(
            project.id, "opportunity", "opportunity-1"
        )
    }
    assert opportunity_ids == {
        "assessment-explicit-opportunity",
        "assessment-inferred-opportunity",
    }


def test_helpdesk_update_delete_and_pull_conflict_paths(store: LocalStore) -> None:
    project = store.create_local_project(name="Helpdesk", project_id="project-1")
    assert store.get_helpdesk_ticket_project_id("missing") is None
    with pytest.raises(KeyError, match="helpdesk ticket not found"):
        store.get_helpdesk_ticket_project_and_version("missing")

    ticket = store.create_helpdesk_ticket(project.id, title="Local ticket")
    unchanged = store.update_helpdesk_ticket(ticket.id)
    assert unchanged.title == "Local ticket"
    updated = store.update_helpdesk_ticket(
        ticket.id,
        title="Edited ticket",
        description="More detail",
        category="bug",
        priority="critical",
        status="in_progress",
    )
    assert updated.title == "Edited ticket"
    assert updated.status == "in_progress"
    with pytest.raises(KeyError, match="helpdesk ticket not found"):
        store.update_helpdesk_ticket("missing", title="Nope")

    outbox = OutboxStore(store)
    outbox.queue_helpdesk_upsert(
        ticket.id,
        project.id,
        title=updated.title,
        status=updated.status,
    )
    store.apply_pull_helpdesk_tickets(
        project.id,
        [
            {"id": ""},
            {
                "id": ticket.id,
                "title": "Server title must not win",
                "version": 6,
                "updated_at": "2025-03-01T00:00:00",
            },
            {"id": "ticket-server", "title": "Server ticket"},
            {
                "id": "ticket-deleted",
                "title": "Deleted ticket",
                "version": 3,
                "is_deleted": True,
            },
        ],
    )

    tickets = {item.id: item for item in store.list_helpdesk_tickets(project.id)}
    assert tickets[ticket.id].title == "Edited ticket"
    assert tickets[ticket.id].version == 6
    assert tickets["ticket-server"].category == "other"
    assert "ticket-deleted" not in tickets

    assert store.soft_delete_helpdesk_ticket("ticket-server")[0] == project.id
    with pytest.raises(KeyError, match="helpdesk ticket not found"):
        store.soft_delete_helpdesk_ticket("missing")
    store.delete_helpdesk_ticket(ticket.id)
    assert store.get_helpdesk_ticket_project_id(ticket.id) is None
