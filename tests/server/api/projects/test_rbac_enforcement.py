"""RBAC enforcement: viewer/member/manager/admin boundaries on real endpoints."""

from __future__ import annotations

from support import add_member, create_item, create_project, register_user


def test_viewer_can_read_but_not_create(api):
    """Viewer role can list risks but is forbidden from creating new ones"""
    admin = register_user(api)
    viewer = register_user(api)
    project = create_project(api, admin)
    add_member(api, project, viewer, "viewer")

    # Viewer can list risks (read)
    r = api.get(f"/projects/{project.id}/risks", headers=viewer.headers)
    assert r.status_code == 200

    # Viewer cannot create a risk (write)
    r = api.post(
        f"/projects/{project.id}/risks",
        json={
            "type": "risk",
            "title": "X",
            "probability": 3,
            "impact": 3,
        },
        headers=viewer.headers,
    )
    assert r.status_code == 403


def test_member_can_create_but_not_delete(api):
    """Member role can create risks but is forbidden from deleting them"""
    admin = register_user(api)
    member = register_user(api)
    project = create_project(api, admin)
    add_member(api, project, member, "member")

    # Member can create (create_item checks for HTTP 201)
    risk = create_item(
        api, project, member, kind="risk", title="R1", probability=4, impact=2
    )

    # Member cannot delete (requires manager)
    r = api.delete(f"/projects/{project.id}/risks/{risk.id}", headers=member.headers)
    assert r.status_code == 403


def test_manager_can_delete(api):
    """Manager role can both create and delete risks"""
    admin = register_user(api)
    manager = register_user(api)
    project = create_project(api, admin)
    add_member(api, project, manager, "manager")

    # Manager creates a risk (create_item checks for HTTP 201)
    risk = create_item(
        api, project, manager, kind="risk", title="R1", probability=3, impact=3
    )

    # Manager can delete
    r = api.delete(f"/projects/{project.id}/risks/{risk.id}", headers=manager.headers)
    assert r.status_code == 204
