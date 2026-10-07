from __future__ import annotations

from support import create_item, create_project, register_user


def test_register_create_project_create_items_and_matrix(api) -> None:
    """Register, create project, add risk + opportunity, and verify matrix counts"""
    user = register_user(api)
    project = create_project(api, user, name="Demo Project")
    create_item(
        api, project, user, kind="risk", title="Risk A", probability=4, impact=3
    )
    create_item(
        api, project, user, kind="opportunity", title="Opp A", probability=2, impact=5
    )

    r = api.get(f"/projects/{project.id}/matrix?kind=both", headers=user.headers)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["kind"] == "both"
    assert payload["risks"][3][2] == 1
    assert payload["opportunities"][1][4] == 1
