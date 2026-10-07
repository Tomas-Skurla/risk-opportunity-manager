"""Sync round-trip tests."""

from __future__ import annotations

from support import (
    create_project,
    new_change,
    newly_accepted,
    pull,
    push,
    register_user,
    replayed,
    results_with,
)


def test_pull_returns_items_created_via_rest(api):
    """Sync pull returns risks that were created through the REST API"""
    user = register_user(api)
    pid = create_project(api, user, name="SyncProject").id

    # Create a risk via REST.
    r = api.post(
        f"/projects/{pid}/risks",
        json={
            "type": "risk",
            "title": "Sync Risk",
            "probability": 4,
            "impact": 3,
        },
        headers=user.headers,
    )
    assert r.status_code == 201
    risk_id = r.json()["id"]

    # Pull via sync.
    r = pull(api, pid, user)
    assert r.status_code == 200
    data = r.json()
    risk_ids = [r["id"] for r in data["risks"]]
    assert risk_id in risk_ids


def test_push_upsert_bumps_version(api):
    """Sync push upsert applies the change and bumps the entity version"""
    user = register_user(api)
    pid = create_project(api, user, name="SyncProject").id

    # Create a risk via REST.
    r = api.post(
        f"/projects/{pid}/risks",
        json={
            "type": "risk",
            "title": "Original",
            "probability": 2,
            "impact": 2,
        },
        headers=user.headers,
    )
    risk_id = r.json()["id"]
    version = r.json()["version"]

    # Push an update via sync.
    r = push(
        api,
        pid,
        user,
        new_change(
            "risk",
            {
                "id": risk_id,
                "title": "Updated via sync",
                "probability": 3,
                "impact": 4,
            },
            base_version=version,
        ),
    )
    assert r.status_code == 200
    result = r.json()
    assert len(newly_accepted(result)) == 1
    assert results_with(result, "error") == []

    # Pull again and verify title/version.
    r = pull(api, pid, user)
    risk = [x for x in r.json()["risks"] if x["id"] == risk_id][0]
    assert risk["title"] == "Updated via sync"
    assert risk["version"] == version + 1


def test_push_duplicate_change_id_is_idempotent(api):
    """Sync push with a duplicate change_id is idempotent (counted as duplicate)"""
    user = register_user(api)
    pid = create_project(api, user, name="SyncProject").id

    r = api.post(
        f"/projects/{pid}/risks",
        json={
            "type": "risk",
            "title": "R",
            "probability": 1,
            "impact": 1,
        },
        headers=user.headers,
    )
    risk_id = r.json()["id"]

    replayed_change = new_change(
        "risk",
        {"id": risk_id, "title": "X", "probability": 2, "impact": 2},
        base_version=1,
    )

    # First push.
    r = push(api, pid, user, replayed_change)
    assert len(newly_accepted(r.json())) == 1

    # Second push with the same change_id.
    r = push(api, pid, user, replayed_change)
    assert len(replayed(r.json())) == 1
    assert len(newly_accepted(r.json())) == 0
