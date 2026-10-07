"""Item CRUD edge cases: duplicate code, stale base_version, filter mutex."""

from __future__ import annotations

import uuid

from support import create_item, create_project, register_user


def test_duplicate_item_code_returns_409(api):
    """Creating a second risk with the same explicit code returns HTTP 409"""
    user = register_user(api)
    project = create_project(api, user)
    create_item(api, project, user, kind="risk", title="First", code="R-DUPLICATE")

    r = api.post(
        f"/projects/{project.id}/risks",
        json={
            "type": "risk",
            "title": "Second",
            "probability": 2,
            "impact": 2,
            "code": "R-DUPLICATE",
        },
        headers=user.headers,
    )
    assert r.status_code == 409, r.text
    assert "code" in r.json()["detail"].lower()


def test_item_patch_with_stale_base_version_returns_409(api):
    """Risk PATCH with stale base_version returns 409 with version_mismatch reason"""
    user = register_user(api)
    project = create_project(api, user)
    risk = create_item(api, project, user, kind="risk", title="Versioned")
    assert risk.version == 1

    r = api.patch(
        f"/projects/{project.id}/risks/{risk.id}",
        json={"title": "Renamed", "base_version": 999},
        headers=user.headers,
    )
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["reason"] == "version_mismatch"
    assert detail["server_version"] == 1


def test_owner_user_id_and_owner_unassigned_are_mutually_exclusive(api):
    """Listing with both owner_user_id and owner_unassigned set returns HTTP 422"""
    user = register_user(api)
    project = create_project(api, user)

    some_uuid = str(uuid.uuid4())
    r = api.get(
        f"/projects/{project.id}/risks",
        params={"owner_user_id": some_uuid, "owner_unassigned": "true"},
        headers=user.headers,
    )
    assert r.status_code == 422, r.text
    assert "owner" in str(r.json()["detail"]).lower()
