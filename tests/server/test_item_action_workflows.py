"""Item and action validation workflows that protect persisted state."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _setup(client: TestClient, *, email: str) -> tuple[dict[str, str], str]:
    registered = client.post(
        "/register",
        json={"email": email, "password": "Password123!"},
    )
    assert registered.status_code == 201, registered.text
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    project = client.post("/projects", json={"name": "P"}, headers=headers)
    assert project.status_code == 201, project.text
    return headers, project.json()["id"]


def _create_item(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    *,
    kind: str,
    title: str,
    **extra,
) -> dict:
    collection = "risks" if kind == "risk" else "opportunities"
    response = client.post(
        f"/projects/{project_id}/{collection}",
        json={
            "type": kind,
            "title": title,
            "probability": 2,
            "impact": 3,
            **extra,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_item_validation_reports_and_status_transitions(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'items.db'}")
    with TestClient(app) as client:
        headers, project_id = _setup(client, email="items@test.com")

        rejected = client.post(
            f"/projects/{project_id}/risks",
            json={
                "type": "risk",
                "title": "Already deleted",
                "probability": 1,
                "impact": 1,
                "status": "deleted",
            },
            headers=headers,
        )
        assert rejected.status_code == 422
        assert "status=deleted" in rejected.json()["detail"]

        happened = _create_item(
            client,
            headers,
            project_id,
            kind="risk",
            title="Incident",
            code="R-INCIDENT",
            status="happened",
            category="operations",
        )
        assert happened["occurred_at"] is not None
        generated = _create_item(
            client,
            headers,
            project_id,
            kind="risk",
            title="Generated code",
            probability=4,
            impact=5,
        )
        opportunity = _create_item(
            client,
            headers,
            project_id,
            kind="opportunity",
            title="Wrong route type",
        )

        missing_id = str(uuid.uuid4())
        assert (
            client.patch(
                f"/projects/{project_id}/risks/{missing_id}",
                json={"title": "Missing"},
                headers=headers,
            ).status_code
            == 404
        )
        assert (
            client.patch(
                f"/projects/{project_id}/risks/{opportunity['id']}",
                json={"title": "Wrong type"},
                headers=headers,
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
            response = client.patch(
                f"/projects/{project_id}/risks/{generated['id']}",
                json=payload,
                headers=headers,
            )
            assert response.status_code == 422, response.text
            assert detail in str(response.json()["detail"])

        duplicate = client.patch(
            f"/projects/{project_id}/risks/{generated['id']}",
            json={"code": "R-INCIDENT"},
            headers=headers,
        )
        assert duplicate.status_code == 409

        transitioned = client.patch(
            f"/projects/{project_id}/risks/{generated['id']}",
            json={"status": "happened", "base_version": generated["version"]},
            headers=headers,
        )
        assert transitioned.status_code == 200, transitioned.text
        assert transitioned.json()["status"] == "happened"

        deleted = client.patch(
            f"/projects/{project_id}/risks/{generated['id']}",
            json={"status": "deleted", "base_version": transitioned.json()["version"]},
            headers=headers,
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["is_deleted"] is True

        assert (
            client.delete(
                f"/projects/{project_id}/risks/{missing_id}", headers=headers
            ).status_code
            == 404
        )
        report = client.get(f"/projects/{project_id}/risks/report", headers=headers)
        assert report.status_code == 200, report.text
        assert report.json()["total"] == 1
        assert report.json()["project_total"] == 1
        assert report.json()["status_counts"] == {"happened": 1}
        assert report.json()["category_counts"] == {"operations": 1}

        empty_project = client.post(
            "/projects", json={"name": "Empty"}, headers=headers
        ).json()["id"]
        empty_report = client.get(
            f"/projects/{empty_project}/risks/report", headers=headers
        ).json()
        assert empty_report["total"] == 0
        assert empty_report["min_score"] is None
        assert empty_report["avg_score"] is None


def test_action_update_validation_and_retargeting(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'actions.db'}")
    with TestClient(app) as client:
        headers, project_id = _setup(client, email="actions-branches@test.com")
        risk = _create_item(client, headers, project_id, kind="risk", title="Outage")
        opportunity = _create_item(
            client,
            headers,
            project_id,
            kind="opportunity",
            title="Expansion",
        )

        missing_target = client.post(
            f"/projects/{project_id}/actions",
            json={
                "opportunity_id": str(uuid.uuid4()),
                "kind": "exploit",
                "title": "Missing target",
            },
            headers=headers,
        )
        assert missing_target.status_code == 404

        created = client.post(
            f"/projects/{project_id}/actions",
            json={
                "opportunity_id": opportunity["id"],
                "kind": "exploit",
                "title": "Use expansion",
                "status": "doing",
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text
        action = created.json()
        assert action["risk_id"] is None
        assert action["opportunity_id"] == opportunity["id"]

        listed = client.get(f"/projects/{project_id}/actions", headers=headers).json()
        assert listed[0]["opportunity_id"] == opportunity["id"]

        missing_action = str(uuid.uuid4())
        assert (
            client.patch(
                f"/projects/{project_id}/actions/{missing_action}",
                json={"title": "Missing"},
                headers=headers,
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
            response = client.patch(
                f"/projects/{project_id}/actions/{action['id']}",
                json=payload,
                headers=headers,
            )
            assert response.status_code == 422, response.text
            assert detail in str(response.json()["detail"])

        retargeted = client.patch(
            f"/projects/{project_id}/actions/{action['id']}",
            json={
                "risk_id": risk["id"],
                "kind": "mitigation",
                "title": "  Mitigate outage  ",
                "description": "Add redundancy",
                "status": "done",
            },
            headers=headers,
        )
        assert retargeted.status_code == 200, retargeted.text
        assert retargeted.json()["risk_id"] == risk["id"]
        assert retargeted.json()["opportunity_id"] is None
        assert retargeted.json()["title"] == "Mitigate outage"
        assert retargeted.json()["version"] == 2

        description_only = client.patch(
            f"/projects/{project_id}/actions/{action['id']}",
            json={"description": "Updated details"},
            headers=headers,
        )
        assert description_only.status_code == 200
        assert description_only.json()["version"] == 3
