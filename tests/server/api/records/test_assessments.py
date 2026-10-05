"""Assessment upsert: create, update, version check, score recalc."""

from __future__ import annotations

import uuid

from support import create_item, create_project, register_user


def test_create_and_update_assessment(api):
    """Create then update an assessment, verifying score recalc and version bump"""
    user = register_user(api)
    project = create_project(api, user)
    risk = create_item(api, project, user, kind="risk", probability=4, impact=3)
    url = f"/projects/{project.id}/risks/{risk.id}/assessment"

    wrong_create_version = api.put(
        url,
        json={"probability": 5, "impact": 4, "base_version": 1},
        headers=user.headers,
    )
    assert wrong_create_version.status_code == 409
    assert wrong_create_version.json()["detail"] == {
        "reason": "version_mismatch",
        "server_version": None,
    }

    # Create assessment
    r = api.put(
        url,
        json={
            "probability": 5,
            "impact": 4,
            "notes": "Very likely",
            "base_version": 0,
        },
        headers=user.headers,
    )
    assert r.status_code == 200
    a = r.json()
    assert a["probability"] == 5
    assert a["impact"] == 4
    assert a["score"] == 20  # 5 * 4
    assert a["version"] == 1

    # Update assessment
    r = api.put(
        url,
        json={
            "probability": 2,
            "impact": 1,
            "notes": "Revised down",
            "base_version": a["version"],
        },
        headers=user.headers,
    )
    assert r.status_code == 200
    a = r.json()
    assert a["score"] == 2  # 2 * 1
    assert a["version"] == 2


def test_list_assessments(api):
    """List assessments for a risk returns the assessments created so far"""
    user = register_user(api)
    project = create_project(api, user)
    risk = create_item(api, project, user, kind="risk", probability=4, impact=3)

    api.put(
        f"/projects/{project.id}/risks/{risk.id}/assessment",
        json={"probability": 3, "impact": 3, "base_version": 0},
        headers=user.headers,
    )

    r = api.get(
        f"/projects/{project.id}/risks/{risk.id}/assessments", headers=user.headers
    )
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_assessment_on_nonexistent_item_returns_404(api):
    """Assessing a non-existent risk returns HTTP 404"""
    user = register_user(api)
    project = create_project(api, user)
    fake_id = str(uuid.uuid4())
    r = api.put(
        f"/projects/{project.id}/risks/{fake_id}/assessment",
        json={"probability": 3, "impact": 3, "base_version": 0},
        headers=user.headers,
    )
    assert r.status_code == 404
