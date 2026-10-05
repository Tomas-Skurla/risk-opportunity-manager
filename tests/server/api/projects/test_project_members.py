"""Project member admin protection and superadmin visibility filtering."""

from __future__ import annotations

from support import create_project, promote_to_superuser, register_user


def test_cannot_remove_or_downgrade_last_admin(api):
    """The last admin of a project cannot be downgraded or removed by themselves"""
    admin = register_user(api)
    project = create_project(api, admin)

    # Try to downgrade the only admin to viewer → 400
    r = api.post(
        f"/projects/{project.id}/members",
        json={"user_email": admin.email, "role": "viewer"},
        headers=admin.headers,
    )
    assert r.status_code == 400, r.text
    assert "last admin" in r.json()["detail"].lower()

    # Try to remove the only admin → 400
    r = api.delete(f"/projects/{project.id}/members/{admin.id}", headers=admin.headers)
    assert r.status_code == 400, r.text
    assert "last admin" in r.json()["detail"].lower()


def test_member_list_hides_superadmin_from_non_superusers(api):
    """GET /members hides superadmin entries from non-superuser callers"""
    admin = register_user(api)
    superuser = register_user(api)
    promote_to_superuser(superuser)
    project = create_project(api, admin)

    # The superuser adds themselves to the project (they bypass non-superuser
    # restrictions and implicitly have admin access via _is_superuser).
    r = api.post(
        f"/projects/{project.id}/members",
        json={"user_email": superuser.email, "role": "member"},
        headers=superuser.headers,
    )
    assert r.status_code == 201, r.text

    # Regular admin (non-superuser) should not see the superuser.
    r = api.get(f"/projects/{project.id}/members", headers=admin.headers)
    assert r.status_code == 200, r.text
    emails = [m["email"] for m in r.json()]
    assert admin.email in emails
    assert superuser.email not in emails

    # The superuser themselves sees both members.
    r = api.get(f"/projects/{project.id}/members", headers=superuser.headers)
    assert r.status_code == 200, r.text
    emails = [m["email"] for m in r.json()]
    assert {admin.email, superuser.email} <= set(emails)
