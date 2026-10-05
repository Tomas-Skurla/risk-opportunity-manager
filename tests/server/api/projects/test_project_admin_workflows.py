"""Project administration workflows across authorization and cleanup boundaries."""

from __future__ import annotations

import uuid

from support import (
    create_item,
    create_project,
    new_password,
    promote_to_superuser,
    register_user,
)

# Server imports follow isolated_app_factory's module reloads.
# pylint: disable=import-outside-toplevel


def test_member_updates_removals_and_superuser_visibility(api) -> None:
    owner = register_user(api)
    member = register_user(api)
    superuser = register_user(api)
    promote_to_superuser(superuser)
    project_id = create_project(api, owner, name="Administration").id
    assert api.get(f"/projects/{project_id}", headers=owner.headers).status_code == 200

    missing_user = api.post(
        f"/projects/{project_id}/members",
        json={"user_email": "missing@example.com", "role": "member"},
        headers=owner.headers,
    )
    assert missing_user.status_code == 404
    protected_add = api.post(
        f"/projects/{project_id}/members",
        json={"user_email": superuser.email, "role": "member"},
        headers=owner.headers,
    )
    assert protected_add.status_code == 403
    added_superuser = api.post(
        f"/projects/{project_id}/members",
        json={"user_email": superuser.email, "role": "member"},
        headers=superuser.headers,
    )
    assert added_superuser.status_code == 201
    protected_remove = api.delete(
        f"/projects/{project_id}/members/{superuser.id}",
        headers=owner.headers,
    )
    assert protected_remove.status_code == 403
    added = api.post(
        f"/projects/{project_id}/members",
        json={"user_email": member.email, "role": "admin"},
        headers=owner.headers,
    )
    assert added.status_code == 201
    assert added.json()["updated"] is False
    updated = api.post(
        f"/projects/{project_id}/members",
        json={"user_email": member.email, "role": "manager"},
        headers=owner.headers,
    )
    assert updated.status_code == 201
    assert updated.json()["updated"] is True

    missing_member = api.delete(
        f"/projects/{project_id}/members/{uuid.uuid4()}", headers=owner.headers
    )
    assert missing_member.status_code == 404
    removed = api.delete(
        f"/projects/{project_id}/members/{member.id}",
        headers=owner.headers,
    )
    assert removed.status_code == 204

    all_projects = api.get("/projects", headers=superuser.headers)
    assert all_projects.status_code == 200
    assert project_id in {entry["id"] for entry in all_projects.json()}
    member_projects = api.get("/projects", headers=owner.headers)
    assert member_projects.status_code == 200
    assert project_id in {entry["id"] for entry in member_projects.json()}
    assert owner.id != superuser.id


def test_superuser_bypass_pruning_and_project_cascade_delete(api) -> None:
    regular = register_user(api)
    superuser = register_user(api)
    promote_to_superuser(superuser)
    project = create_project(api, regular, name="Disposable")
    project_id = project.id
    create_item(api, project, regular, kind="risk", title="Cascade me")

    project_admin_prune = api.post(
        f"/admin/projects/{project_id}/maintenance/prune?days=0",
        headers=regular.headers,
    )
    assert project_admin_prune.status_code == 403

    default_prune = api.post(
        f"/admin/projects/{project_id}/maintenance/prune?days=0",
        headers=superuser.headers,
    )

    assert default_prune.status_code == 200
    assert default_prune.json()["ok"] is True
    bounded_prune = api.post(
        f"/admin/projects/{project_id}/maintenance/prune?days=99999",
        headers=superuser.headers,
    )
    assert bounded_prune.status_code == 200
    missing_prune = api.post(
        f"/admin/projects/{uuid.uuid4()}/maintenance/prune",
        headers=superuser.headers,
    )
    assert missing_prune.status_code == 404

    forbidden = api.delete(f"/admin/projects/{project_id}", headers=regular.headers)
    assert forbidden.status_code == 403
    missing_id = uuid.uuid4()
    assert (
        api.get(f"/projects/{missing_id}", headers=superuser.headers).status_code == 404
    )
    assert (
        api.delete(
            f"/admin/projects/{missing_id}", headers=superuser.headers
        ).status_code
        == 404
    )

    deleted = api.delete(f"/admin/projects/{project_id}", headers=superuser.headers)
    assert deleted.status_code == 204
    assert (
        api.get(f"/projects/{project_id}", headers=superuser.headers).status_code == 404
    )

    own_project = create_project(api, superuser, name="Superuser project").id
    downgraded = api.post(
        f"/projects/{own_project}/members",
        json={"user_email": superuser.email, "role": "viewer"},
        headers=superuser.headers,
    )
    assert downgraded.status_code == 201
    assert downgraded.json()["updated"] is True
    assert regular.id != superuser.id


def test_every_admin_route_requires_a_superuser(api) -> None:
    """The router-wide check covers every /admin route, including future ones."""
    from fastapi.routing import APIRoute
    from riskapp_server.auth.service import require_superuser

    app = api.app

    admin_routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/admin/")
    ]
    assert admin_routes
    for route in admin_routes:
        assert any(
            dep.dependency is require_superuser for dep in route.dependencies
        ), route.path


def test_admin_routes_reject_regular_users_and_old_paths_are_gone(api) -> None:
    regular = register_user(api)
    project_id = create_project(api, regular, name="Owned by a project admin").id
    user_id = regular.id

    admin_calls = [
        ("DELETE", f"/admin/projects/{project_id}", None),
        ("POST", f"/admin/projects/{project_id}/maintenance/prune", None),
        ("POST", f"/admin/users/{user_id}/deactivate", None),
        ("POST", f"/admin/users/{user_id}/activate", None),
        (
            "POST",
            f"/admin/users/{user_id}/set-password",
            {"new_password": new_password()},
        ),
    ]
    for method, path, body in admin_calls:
        anonymous = api.request(method, path, json=body)
        assert anonymous.status_code == 401, path
        # Being the project's own admin grants no global administration.
        as_project_admin = api.request(method, path, json=body, headers=regular.headers)
        assert as_project_admin.status_code == 403, path

    # The previous addresses are retired rather than kept as aliases.
    old_delete = api.delete(f"/projects/{project_id}", headers=regular.headers)
    assert old_delete.status_code == 405
    old_prune = api.post(
        f"/projects/{project_id}/maintenance/prune", headers=regular.headers
    )
    assert old_prune.status_code == 404
    assert (
        api.get(f"/projects/{project_id}", headers=regular.headers).status_code == 200
    )
