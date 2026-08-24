"""Regression tests for sync batch idempotency and safe failures."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from riskapp_server.sync import engine


def _register_and_create_project(client: TestClient) -> tuple[str, dict[str, str]]:
    response = client.post(
        "/register",
        json={"email": "batch-sync@test.com", "password": "Password123!"},
    )
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    response = client.post("/projects", json={"name": "Batch Sync"}, headers=headers)
    return response.json()["id"], headers


def test_duplicate_change_id_in_one_push_is_applied_once(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'batch-sync.db'}")
    with TestClient(app) as client:
        project_id, headers = _register_and_create_project(client)
        change_id = str(uuid.uuid4())
        risk_id = str(uuid.uuid4())
        response = client.post(
            f"/projects/{project_id}/sync/push",
            json={
                "project_id": project_id,
                "changes": [
                    {
                        "change_id": change_id,
                        "entity": "risk",
                        "op": "upsert",
                        "base_version": 0,
                        "record": {
                            "id": risk_id,
                            "title": "First value",
                            "probability": 2,
                            "impact": 3,
                        },
                    },
                    {
                        "change_id": change_id,
                        "entity": "risk",
                        "op": "upsert",
                        "base_version": 0,
                        "record": {
                            "id": risk_id,
                            "title": "Must not be applied",
                            "probability": 5,
                            "impact": 5,
                        },
                    },
                ],
            },
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["accepted"] == 1
        assert response.json()["duplicates"] == 1
        assert response.json()["duplicate_change_ids"] == [change_id]

        response = client.post(
            f"/projects/{project_id}/sync/pull",
            json={"project_id": project_id, "since": "2000-01-01T00:00:00"},
            headers=headers,
        )
        risk = next(item for item in response.json()["risks"] if item["id"] == risk_id)
        assert risk["title"] == "First value"


def test_commit_failure_rolls_back_without_exposing_database_details(
    monkeypatch,
) -> None:
    class FailingSession:
        rolled_back = False

        def commit(self) -> None:
            raise RuntimeError("database password=interview-secret")

        def rollback(self) -> None:
            self.rolled_back = True

    session = FailingSession()
    monkeypatch.setattr(engine, "ensure_member", lambda *_args: "member")

    with pytest.raises(HTTPException) as caught:
        engine.push_changes(session, uuid.uuid4(), uuid.uuid4(), [])

    assert caught.value.status_code == 500
    assert caught.value.detail == "Sync push commit failed"
    assert "interview-secret" not in str(caught.value.detail)
    assert session.rolled_back is True
