from __future__ import annotations

import uuid

from support import (
    create_project,
    new_change,
    newly_accepted,
    pull,
    push,
    register_user,
    results_with,
)


def test_helpdesk_rest_crud_and_soft_delete(api):
    """Helpdesk tickets support full REST CRUD with soft-delete"""
    user = register_user(api)
    project = create_project(api, user, name="Helpdesk Project")

    r = api.post(
        f"/projects/{project.id}/helpdesk/tickets",
        json={
            "title": "Export fails",
            "description": "CSV export crashes",
            "category": "bug",
            "priority": "high",
            "reporter_email": "reporter@example.com",
        },
        headers=user.headers,
    )
    assert r.status_code == 201, r.text
    ticket = r.json()
    assert ticket["status"] == "open"
    assert ticket["version"] == 1

    r = api.patch(
        f"/projects/{project.id}/helpdesk/tickets/{ticket['id']}",
        json={"status": "in_progress", "base_version": 1},
        headers=user.headers,
    )
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["status"] == "in_progress"
    assert updated["version"] == 2
    r = api.get(f"/projects/{project.id}/helpdesk/tickets", headers=user.headers)
    assert r.status_code == 200, r.text
    assert [x["id"] for x in r.json()] == [ticket["id"]]
    r = api.delete(
        f"/projects/{project.id}/helpdesk/tickets/{ticket['id']}", headers=user.headers
    )
    assert r.status_code == 204, r.text
    r = api.get(f"/projects/{project.id}/helpdesk/tickets", headers=user.headers)
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_helpdesk_sync_create_allows_zero_but_update_requires_current_version(api):
    """Zero is create-only; an existing ticket requires its current version."""
    user = register_user(api)
    project = create_project(api, user, name="Helpdesk Project")

    ticket_id = str(uuid.uuid4())
    r = push(
        api,
        project.id,
        user,
        new_change(
            "helpdesk_ticket",
            {
                "id": ticket_id,
                "title": "Sync me",
                "description": "Created offline",
                "category": "bug",
                "priority": "medium",
                "status": "open",
                "reporter_email": "sync@example.com",
            },
            base_version=0,
        ),
    )
    assert r.status_code == 200, r.text
    assert len(newly_accepted(r.json())) == 1

    r = pull(api, project.id, user)
    assert r.status_code == 200, r.text
    pulled = r.json()["helpdesk_tickets"]
    assert len(pulled) == 1
    assert pulled[0]["id"] == ticket_id
    assert pulled[0]["title"] == "Sync me"

    r = push(
        api,
        project.id,
        user,
        new_change(
            "helpdesk_ticket",
            {
                "id": ticket_id,
                "title": "Sync me v2",
                "status": "resolved",
            },
            base_version=0,
        ),
    )
    assert r.status_code == 200, r.text
    rejected = r.json()
    assert len(newly_accepted(rejected)) == 0
    assert results_with(rejected, "conflict")[0]["reason"] == "base_version_required"
    assert results_with(rejected, "conflict")[0]["server_version"] == 1

    r = push(
        api,
        project.id,
        user,
        new_change(
            "helpdesk_ticket",
            {
                "id": ticket_id,
                "title": "Sync me v2",
                "status": "resolved",
            },
            base_version=1,
        ),
    )
    assert r.status_code == 200, r.text
    assert len(newly_accepted(r.json())) == 1
    r = pull(api, project.id, user)
    assert r.status_code == 200, r.text
    pulled = {x["id"]: x for x in r.json()["helpdesk_tickets"]}
    assert pulled[ticket_id]["title"] == "Sync me v2"
    assert pulled[ticket_id]["status"] == "resolved"


def test_helpdesk_sync_delete_marks_deleted_and_is_pulled(api):
    """Helpdesk sync delete marks ticket deleted and is surfaced on pull"""
    user = register_user(api)
    project = create_project(api, user, name="Helpdesk Project")
    r = api.post(
        f"/projects/{project.id}/helpdesk/tickets",
        json={"title": "Delete me"},
        headers=user.headers,
    )
    assert r.status_code == 201, r.text
    ticket = r.json()

    r = push(
        api,
        project.id,
        user,
        new_change(
            "helpdesk_ticket", {"id": ticket["id"]}, op="delete", base_version=0
        ),
    )
    assert r.status_code == 200, r.text
    rejected = r.json()
    assert len(newly_accepted(rejected)) == 0
    assert results_with(rejected, "conflict")[0]["reason"] == "base_version_required"
    assert results_with(rejected, "conflict")[0]["server_version"] == 1

    r = push(
        api,
        project.id,
        user,
        new_change(
            "helpdesk_ticket", {"id": ticket["id"]}, op="delete", base_version=1
        ),
    )
    assert r.status_code == 200, r.text
    assert len(newly_accepted(r.json())) == 1
    r = pull(api, project.id, user)
    assert r.status_code == 200, r.text
    pulled = {x["id"]: x for x in r.json()["helpdesk_tickets"]}
    assert pulled[ticket["id"]]["is_deleted"] is True


def test_helpdesk_update_requires_matching_base_version(api):
    """Helpdesk PATCH with stale base_version returns HTTP 409 with version_mismatch"""
    user = register_user(api)
    project_id = create_project(api, user, name="P").id
    created = api.post(
        f"/projects/{project_id}/helpdesk/tickets",
        json={"title": "Broken export", "category": "bug", "priority": "high"},
        headers=user.headers,
    )
    assert created.status_code == 201
    ticket = created.json()
    resp = api.patch(
        f"/projects/{project_id}/helpdesk/tickets/{ticket['id']}",
        json={"title": "Broken export 2", "base_version": 999},
        headers=user.headers,
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["reason"] == "version_mismatch"
    assert detail["server_version"] == 1
