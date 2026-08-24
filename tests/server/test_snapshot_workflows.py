"""Snapshot aliases, empty states, bounds, and history filters."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _setup(client: TestClient) -> tuple[dict[str, str], str]:
    registered = client.post(
        "/register",
        json={"email": "snapshot-branches@test.com", "password": "Password123!"},
    )
    assert registered.status_code == 201, registered.text
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    project = client.post("/projects", json={"name": "Snapshots"}, headers=headers)
    assert project.status_code == 201, project.text
    return headers, project.json()["id"]


def _create_item(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    *,
    kind: str,
    title: str,
) -> None:
    collection = "risks" if kind == "risk" else "opportunities"
    response = client.post(
        f"/projects/{project_id}/{collection}",
        json={
            "type": kind,
            "title": title,
            "probability": 3,
            "impact": 4,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text


def test_snapshot_empty_states_aliases_and_history_filters(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'snapshots.db'}")
    with TestClient(app) as client:
        headers, project_id = _setup(client)

        latest_empty = client.get(
            f"/projects/{project_id}/snapshots/latest?kind=risks", headers=headers
        )
        assert latest_empty.status_code == 404
        top_empty = client.get(
            f"/projects/{project_id}/snapshots/{uuid.uuid4()}/top",
            headers=headers,
        )
        assert top_empty.status_code == 404
        history_empty = client.get(
            f"/projects/{project_id}/top-history?kind=risks", headers=headers
        )
        assert history_empty.status_code == 200
        assert history_empty.json() == []

        invalid_create = client.post(
            f"/projects/{project_id}/snapshots?kind=invalid", headers=headers
        )
        assert invalid_create.status_code == 400

        empty_project = client.post(
            "/projects", json={"name": "Empty"}, headers=headers
        ).json()["id"]
        empty_snapshot = client.post(
            f"/projects/{empty_project}/snapshots?kind=both", headers=headers
        )
        assert empty_snapshot.status_code == 201
        assert empty_snapshot.json()["risks"] == 0
        assert empty_snapshot.json()["opportunities"] == 0

        _create_item(client, headers, project_id, kind="risk", title="Availability")
        _create_item(
            client, headers, project_id, kind="opportunity", title="Automation"
        )

        both = client.post(
            f"/projects/{project_id}/snapshots?kind=all", headers=headers
        )
        assert both.status_code == 201, both.text
        assert both.json()["risks"] == 1
        assert both.json()["opportunities"] == 1

        opportunity_only = client.post(
            f"/projects/{project_id}/snapshots?kind=opps", headers=headers
        )
        assert opportunity_only.status_code == 201, opportunity_only.text
        opportunity_batch = opportunity_only.json()
        assert opportunity_batch["risks"] == 0
        assert opportunity_batch["opportunities"] == 1

        latest = client.get(
            f"/projects/{project_id}/snapshots/latest?kind=opportunity",
            headers=headers,
        )
        assert latest.status_code == 200, latest.text
        assert latest.json()["batch_id"] == opportunity_batch["batch_id"]
        assert latest.json()["kind"] == "opportunity"

        top = client.get(
            f"/projects/{project_id}/snapshots/{opportunity_batch['batch_id']}/top",
            params={"kind": "opportunity", "limit": 0},
            headers=headers,
        )
        assert top.status_code == 200, top.text
        assert [item["title"] for item in top.json()["top"]] == ["Automation"]
        top_large_limit = client.get(
            f"/projects/{project_id}/snapshots/{opportunity_batch['batch_id']}/top",
            params={"kind": "opportunity", "limit": 1000},
            headers=headers,
        )
        assert top_large_limit.status_code == 200

        invalid_latest = client.get(
            f"/projects/{project_id}/snapshots/latest?kind=unknown", headers=headers
        )
        assert invalid_latest.status_code == 400
        invalid_history = client.get(
            f"/projects/{project_id}/top-history?kind=unknown", headers=headers
        )
        assert invalid_history.status_code == 400

        captured_at = opportunity_batch["captured_at"]
        history = client.get(
            f"/projects/{project_id}/top-history",
            params={
                "kind": "opp",
                "limit": 0,
                "from_ts": captured_at,
                "to_ts": captured_at,
            },
            headers=headers,
        )
        assert history.status_code == 200, history.text
        assert len(history.json()) == 1
        assert history.json()[0]["top"][0]["title"] == "Automation"
