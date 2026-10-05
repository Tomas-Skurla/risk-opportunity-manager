"""Action router: target validation, list, RBAC delete."""

from __future__ import annotations

from support import add_member, create_item, create_project, register_user


def test_action_target_type_mismatch_returns_400(api):
    """An opportunity passed as a risk target returns HTTP 400."""
    owner = register_user(api)
    project = create_project(api, owner)

    opp = create_item(api, project, owner, kind="opportunity", title="Reuse components")

    # Pass the opportunity id under risk_id → 400 (target type mismatch)
    r = api.post(
        f"/projects/{project.id}/actions",
        json={
            "risk_id": opp.id,
            "kind": "mitigation",
            "title": "Wrong target kind",
        },
        headers=owner.headers,
    )
    assert r.status_code == 400, r.text
    assert "expected risk" in r.json()["detail"]

    # Provide neither → 400 from the router ("exactly one of ...").
    r = api.post(
        f"/projects/{project.id}/actions",
        json={"kind": "mitigation", "title": "No target"},
        headers=owner.headers,
    )
    assert r.status_code == 400, r.text


def test_member_creates_action_but_only_manager_deletes(api):
    """Member can create an action but only manager+ can delete it"""
    admin = register_user(api)
    member = register_user(api)
    manager = register_user(api)
    project = create_project(api, admin)
    add_member(api, project, member, "member")
    add_member(api, project, manager, "manager")

    risk = create_item(
        api, project, admin, kind="risk", title="Outage", probability=4, impact=4
    )

    # Member creates an action.
    r = api.post(
        f"/projects/{project.id}/actions",
        json={
            "risk_id": risk.id,
            "kind": "mitigation",
            "title": "Add backup server",
        },
        headers=member.headers,
    )
    assert r.status_code == 201, r.text
    action_id = r.json()["id"]

    # Member is forbidden from deleting (delete requires manager+).
    r = api.delete(
        f"/projects/{project.id}/actions/{action_id}", headers=member.headers
    )
    assert r.status_code == 403

    # Manager soft-deletes.
    r = api.delete(
        f"/projects/{project.id}/actions/{action_id}", headers=manager.headers
    )
    assert r.status_code == 204

    # The action no longer appears in the list.
    r = api.get(f"/projects/{project.id}/actions", headers=admin.headers)
    assert r.status_code == 200
    assert action_id not in [a["id"] for a in r.json()]
