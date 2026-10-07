"""Search wildcard escaping."""

from __future__ import annotations

from support import create_item, create_project, register_user


def test_search_for_percent_does_not_match_everything(api):
    """Search for literal '%' is escaped and does not match every record"""
    user = register_user(api)
    project = create_project(api, user)
    create_item(api, project, user, kind="risk", title="Server outage")
    create_item(api, project, user, kind="risk", title="Data loss")
    literal = create_item(api, project, user, kind="risk", title="Budget 100% overrun")

    # A literal "%" should match only the title that contains it.
    r = api.get(
        f"/projects/{project.id}/risks?search=%25",  # %25 is URL-encoded "%"
        headers=user.headers,
    )
    assert r.status_code == 200
    assert [item["id"] for item in r.json()] == [literal.id]


def test_search_for_underscore_does_not_match_single_char(api):
    """Search for literal '_' is escaped and does not match arbitrary single chars"""
    user = register_user(api)
    project = create_project(api, user)
    create_item(api, project, user, kind="risk", title="ABC")
    literal = create_item(api, project, user, kind="risk", title="ABC_DEF")

    # "_" should match the literal underscore, not any arbitrary character.
    r = api.get(f"/projects/{project.id}/risks?search=_", headers=user.headers)
    assert r.status_code == 200
    assert [item["id"] for item in r.json()] == [literal.id]
