"""Item and action validation workflows that protect persisted state."""

from __future__ import annotations

import uuid

from support import create_item, create_project, register_user


def test_item_validation_reports_and_status_transitions(api) -> None:
    user = register_user(api)
    project = create_project(api, user)
    project_id = project.id
    rejected = api.post(
        f"/projects/{project_id}/risks",
        json={
            "type": "risk",
            "title": "Already deleted",
            "probability": 1,
            "impact": 1,
            "status": "deleted",
        },
        headers=user.headers,
    )
    assert rejected.status_code == 422
    assert "status=deleted" in rejected.json()["detail"]

    happened = create_item(
        api,
        project,
        user,
        kind="risk",
        title="Incident",
        code="R-INCIDENT",
        status="happened",
        category="operations",
    )
    assert happened.data["occurred_at"] is not None
    generated = create_item(
        api,
        project,
        user,
        kind="risk",
        title="Generated code",
        probability=4,
        impact=5,
    )
    opportunity = create_item(
        api,
        project,
        user,
        kind="opportunity",
        title="Wrong route type",
    )
    missing_id = str(uuid.uuid4())
    assert (
        api.patch(
            f"/projects/{project_id}/risks/{missing_id}",
            json={"title": "Missing", "base_version": 1},
            headers=user.headers,
        ).status_code
        == 404
    )
    assert (
        api.patch(
            f"/projects/{project_id}/risks/{opportunity.id}",
            json={"title": "Wrong type", "base_version": 1},
            headers=user.headers,
        ).status_code
        == 404
    )
    invalid_updates = [
        ({"code": None}, "code cannot be null"),
        ({"title": None}, "title cannot be null"),
        ({"title": "   "}, "title cannot be blank"),
        ({"probability": None}, "probability cannot be null"),
        ({"identified_at": None}, "identified_at cannot be null"),
    ]
    for payload, detail in invalid_updates:
        response = api.patch(
            f"/projects/{project_id}/risks/{generated.id}",
            json={**payload, "base_version": generated.version},
            headers=user.headers,
        )
        assert response.status_code == 422, response.text
        assert detail in str(response.json()["detail"])

    duplicate = api.patch(
        f"/projects/{project_id}/risks/{generated.id}",
        json={"code": "R-INCIDENT", "base_version": generated.version},
        headers=user.headers,
    )
    assert duplicate.status_code == 409
    transitioned = api.patch(
        f"/projects/{project_id}/risks/{generated.id}",
        json={"status": "happened", "base_version": generated.version},
        headers=user.headers,
    )
    assert transitioned.status_code == 200, transitioned.text
    assert transitioned.json()["status"] == "happened"
    deleted = api.patch(
        f"/projects/{project_id}/risks/{generated.id}",
        json={"status": "deleted", "base_version": transitioned.json()["version"]},
        headers=user.headers,
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["is_deleted"] is True

    assert (
        api.delete(
            f"/projects/{project_id}/risks/{missing_id}", headers=user.headers
        ).status_code
        == 404
    )
    report = api.get(f"/projects/{project_id}/risks/report", headers=user.headers)
    assert report.status_code == 200, report.text
    assert report.json()["total"] == 1
    assert report.json()["project_total"] == 1
    assert report.json()["status_counts"] == {"happened": 1}
    assert report.json()["category_counts"] == {"operations": 1}

    empty_project = create_project(api, user, name="Empty").id
    empty_report = api.get(
        f"/projects/{empty_project}/risks/report", headers=user.headers
    ).json()
    assert empty_report["total"] == 0
    assert empty_report["min_score"] is None
    assert empty_report["avg_score"] is None


def test_action_update_validation_and_retargeting(api) -> None:
    user = register_user(api)
    project = create_project(api, user)
    project_id = project.id
    risk = create_item(api, project, user, kind="risk", title="Outage")
    opportunity = create_item(
        api,
        project,
        user,
        kind="opportunity",
        title="Expansion",
    )
    missing_target = api.post(
        f"/projects/{project_id}/actions",
        json={
            "opportunity_id": str(uuid.uuid4()),
            "kind": "exploit",
            "title": "Missing target",
        },
        headers=user.headers,
    )
    assert missing_target.status_code == 404
    created = api.post(
        f"/projects/{project_id}/actions",
        json={
            "opportunity_id": opportunity.id,
            "kind": "exploit",
            "title": "Use expansion",
            "status": "doing",
        },
        headers=user.headers,
    )
    assert created.status_code == 201, created.text
    action = created.json()
    assert action["risk_id"] is None
    assert action["opportunity_id"] == opportunity.id

    listed = api.get(f"/projects/{project_id}/actions", headers=user.headers).json()
    assert listed[0]["opportunity_id"] == opportunity.id

    missing_action = str(uuid.uuid4())
    assert (
        api.patch(
            f"/projects/{project_id}/actions/{missing_action}",
            json={"title": "Missing", "base_version": 1},
            headers=user.headers,
        ).status_code
        == 404
    )
    invalid_updates = [
        ({"kind": None}, "kind cannot be null"),
        ({"status": None}, "status cannot be null"),
        ({"title": None}, "title cannot be null"),
        ({"title": "  "}, "title cannot be blank"),
    ]
    for payload, detail in invalid_updates:
        response = api.patch(
            f"/projects/{project_id}/actions/{action['id']}",
            json={**payload, "base_version": action["version"]},
            headers=user.headers,
        )
        assert response.status_code == 422, response.text
        assert detail in str(response.json()["detail"])
    retargeted = api.patch(
        f"/projects/{project_id}/actions/{action['id']}",
        json={
            "risk_id": risk.id,
            "kind": "mitigation",
            "title": "  Mitigate outage  ",
            "description": "Add redundancy",
            "status": "done",
            "base_version": action["version"],
        },
        headers=user.headers,
    )
    assert retargeted.status_code == 200, retargeted.text
    assert retargeted.json()["risk_id"] == risk.id
    assert retargeted.json()["opportunity_id"] is None
    assert retargeted.json()["title"] == "Mitigate outage"
    assert retargeted.json()["version"] == 2

    description_only = api.patch(
        f"/projects/{project_id}/actions/{action['id']}",
        json={
            "description": "Updated details",
            "base_version": retargeted.json()["version"],
        },
        headers=user.headers,
    )
    assert description_only.status_code == 200
    assert description_only.json()["version"] == 3
