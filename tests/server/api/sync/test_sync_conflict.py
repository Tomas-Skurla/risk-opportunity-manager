"""Sync: version mismatch → conflict, not a silent overwrite."""

from __future__ import annotations

from support import (
    create_item,
    create_project,
    new_change,
    newly_accepted,
    push,
    register_user,
    results_with,
)


def test_push_with_stale_base_version_returns_conflict(api):
    """Sync push with a stale base_version returns a version_mismatch conflict"""
    user = register_user(api)
    project = create_project(api, user)
    pid = project.id
    risk = create_item(
        api, project, user, kind="risk", title="R", probability=3, impact=3
    )
    risk_id = risk.id
    assert risk.version == 1

    # Push update claiming base_version=1 → succeeds, bumps to 2
    r = push(
        api,
        pid,
        user,
        new_change(
            "risk",
            {
                "id": risk_id,
                "title": "V2",
                "probability": 3,
                "impact": 3,
            },
            base_version=1,
        ),
    )
    assert len(newly_accepted(r.json())) == 1

    # Push another update still claiming base_version=1 → conflict
    r = push(
        api,
        pid,
        user,
        new_change(
            "risk",
            {
                "id": risk_id,
                "title": "Stale",
                "probability": 3,
                "impact": 3,
            },
            base_version=1,
        ),
    )
    result = r.json()
    assert len(newly_accepted(result)) == 0
    conflicts = results_with(result, "conflict")
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict["reason"] == "version_mismatch"
    assert conflict["server_version"] == 2
    assert conflict["server_record"]["id"] == risk_id
    assert conflict["server_record"]["title"] == "V2"
    assert conflict["server_record"]["version"] == 2
    assert conflict["server_updated_at"]
