"""Snapshot aliases, empty states, bounds, and history filters."""

from __future__ import annotations

import uuid

from support import create_item, create_project, register_user


def test_snapshot_empty_states_aliases_and_history_filters(api) -> None:
    user = register_user(api)
    project = create_project(api, user, name="Snapshots")
    project_id = project.id
    latest_empty = api.get(
        f"/projects/{project_id}/snapshots/latest?kind=risks", headers=user.headers
    )
    assert latest_empty.status_code == 404
    top_empty = api.get(
        f"/projects/{project_id}/snapshots/{uuid.uuid4()}/top",
        headers=user.headers,
    )
    assert top_empty.status_code == 404
    history_empty = api.get(
        f"/projects/{project_id}/top-history?kind=risks", headers=user.headers
    )
    assert history_empty.status_code == 200
    assert history_empty.json() == []
    invalid_create = api.post(
        f"/projects/{project_id}/snapshots?kind=invalid", headers=user.headers
    )
    assert invalid_create.status_code == 400
    empty_project = create_project(api, user, name="Empty").id
    empty_snapshot = api.post(
        f"/projects/{empty_project}/snapshots?kind=both", headers=user.headers
    )
    assert empty_snapshot.status_code == 201
    assert empty_snapshot.json()["risks"] == 0
    assert empty_snapshot.json()["opportunities"] == 0
    create_item(api, project, user, kind="risk", title="Availability")
    create_item(api, project, user, kind="opportunity", title="Automation")
    both = api.post(f"/projects/{project_id}/snapshots?kind=all", headers=user.headers)
    assert both.status_code == 201, both.text
    assert both.json()["risks"] == 1
    assert both.json()["opportunities"] == 1
    opportunity_only = api.post(
        f"/projects/{project_id}/snapshots?kind=opps", headers=user.headers
    )
    assert opportunity_only.status_code == 201, opportunity_only.text
    opportunity_batch = opportunity_only.json()
    assert opportunity_batch["risks"] == 0
    assert opportunity_batch["opportunities"] == 1

    latest = api.get(
        f"/projects/{project_id}/snapshots/latest?kind=opportunity",
        headers=user.headers,
    )
    assert latest.status_code == 200, latest.text
    assert latest.json()["batch_id"] == opportunity_batch["batch_id"]
    assert latest.json()["kind"] == "opportunity"

    top = api.get(
        f"/projects/{project_id}/snapshots/{opportunity_batch['batch_id']}/top",
        params={"kind": "opportunity", "limit": 0},
        headers=user.headers,
    )
    assert top.status_code == 200, top.text
    assert [item["title"] for item in top.json()["top"]] == ["Automation"]
    top_large_limit = api.get(
        f"/projects/{project_id}/snapshots/{opportunity_batch['batch_id']}/top",
        params={"kind": "opportunity", "limit": 1000},
        headers=user.headers,
    )
    assert top_large_limit.status_code == 200
    invalid_latest = api.get(
        f"/projects/{project_id}/snapshots/latest?kind=unknown", headers=user.headers
    )
    assert invalid_latest.status_code == 400
    invalid_history = api.get(
        f"/projects/{project_id}/top-history?kind=unknown", headers=user.headers
    )
    assert invalid_history.status_code == 400

    captured_at = opportunity_batch["captured_at"]
    history = api.get(
        f"/projects/{project_id}/top-history",
        params={
            "kind": "opp",
            "limit": 0,
            "from_ts": captured_at,
            "to_ts": captured_at,
        },
        headers=user.headers,
    )
    assert history.status_code == 200, history.text
    assert len(history.json()) == 1
    assert history.json()[0]["top"][0]["title"] == "Automation"
