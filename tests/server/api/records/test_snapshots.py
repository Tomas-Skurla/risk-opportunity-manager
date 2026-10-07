"""Snapshot router: create, latest, top."""

from __future__ import annotations

from support import create_item, create_project, register_user


def test_create_snapshot_and_fetch_top_history(api):
    """Snapshot create returns counts and the top endpoint orders items by score desc"""
    user = register_user(api)
    project = create_project(api, user, name="Snap Project")

    # Three risks with distinct scores so ordering is unambiguous.
    create_item(api, project, user, kind="risk", title="Low", probability=1, impact=2)
    create_item(api, project, user, kind="risk", title="Mid", probability=3, impact=4)
    create_item(
        api, project, user, kind="risk", title="Critical", probability=5, impact=5
    )

    r = api.post(f"/projects/{project.id}/snapshots?kind=risks", headers=user.headers)
    assert r.status_code == 201, r.text
    snap = r.json()
    batch_id = snap["batch_id"]
    assert snap["risks"] == 3
    assert snap["opportunities"] == 0

    r = api.get(
        f"/projects/{project.id}/snapshots/latest?kind=risks", headers=user.headers
    )
    assert r.status_code == 200, r.text
    latest = r.json()
    assert latest["batch_id"] == batch_id
    assert latest["kind"] == "risk"
    assert latest["count"] == 3

    r = api.get(
        f"/projects/{project.id}/snapshots/{batch_id}/top?kind=risk&limit=2",
        headers=user.headers,
    )
    assert r.status_code == 200, r.text
    top = r.json()["top"]
    assert [t["title"] for t in top] == ["Critical", "Mid"]
    assert top[0]["score"] == 25
    assert top[1]["score"] == 12

    r = api.get(
        f"/projects/{project.id}/snapshots/latest?kind=bogus", headers=user.headers
    )
    assert r.status_code == 400
