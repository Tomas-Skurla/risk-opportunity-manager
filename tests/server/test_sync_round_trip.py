"""Sync round-trip tests."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _setup(c):
    """Register a user and create a project."""
    r = c.post(
        "/register",
        json={"email": "sync@test.com", "password": "Password123!"},
    )
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    r = c.post("/projects", json={"name": "SyncProject"}, headers=h)
    pid = r.json()["id"]
    return token, pid, h


def test_pull_returns_items_created_via_rest(tmp_path, isolated_app_factory):
    """Sync pull returns risks that were created through the REST API"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'sync.db'}")
    with TestClient(app) as c:
        token, pid, h = _setup(c)

        # Create a risk via REST.
        r = c.post(
            f"/projects/{pid}/risks",
            json={
                "type": "risk",
                "title": "Sync Risk",
                "probability": 4,
                "impact": 3,
            },
            headers=h,
        )
        assert r.status_code == 201
        risk_id = r.json()["id"]

        # Pull via sync.
        r = c.post(
            f"/projects/{pid}/sync/pull",
            json={"project_id": pid, "since": "2000-01-01T00:00:00"},
            headers=h,
        )
        assert r.status_code == 200
        data = r.json()
        risk_ids = [r["id"] for r in data["risks"]]
        assert risk_id in risk_ids


def test_push_upsert_bumps_version(tmp_path, isolated_app_factory):
    """Sync push upsert applies the change and bumps the entity version"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'sync2.db'}")
    with TestClient(app) as c:
        token, pid, h = _setup(c)

        # Create a risk via REST.
        r = c.post(
            f"/projects/{pid}/risks",
            json={
                "type": "risk",
                "title": "Original",
                "probability": 2,
                "impact": 2,
            },
            headers=h,
        )
        risk_id = r.json()["id"]
        version = r.json()["version"]

        # Push an update via sync.
        change_id = str(uuid.uuid4())
        r = c.post(
            f"/projects/{pid}/sync/push",
            json={
                "project_id": pid,
                "changes": [
                    {
                        "change_id": change_id,
                        "entity": "risk",
                        "op": "upsert",
                        "base_version": version,
                        "record": {
                            "id": risk_id,
                            "title": "Updated via sync",
                            "probability": 3,
                            "impact": 4,
                        },
                    }
                ],
            },
            headers=h,
        )
        assert r.status_code == 200
        result = r.json()
        assert result["accepted"] == 1
        assert result["errors"] == []

        # Pull again and verify title/version.
        r = c.post(
            f"/projects/{pid}/sync/pull",
            json={"project_id": pid, "since": "2000-01-01T00:00:00"},
            headers=h,
        )
        risk = [x for x in r.json()["risks"] if x["id"] == risk_id][0]
        assert risk["title"] == "Updated via sync"
        assert risk["version"] == version + 1


def test_push_duplicate_change_id_is_idempotent(tmp_path, isolated_app_factory):
    """Sync push with a duplicate change_id is idempotent (counted as duplicate)"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'sync3.db'}")
    with TestClient(app) as c:
        token, pid, h = _setup(c)

        r = c.post(
            f"/projects/{pid}/risks",
            json={
                "type": "risk",
                "title": "R",
                "probability": 1,
                "impact": 1,
            },
            headers=h,
        )
        risk_id = r.json()["id"]

        change_id = str(uuid.uuid4())
        payload = {
            "project_id": pid,
            "changes": [
                {
                    "change_id": change_id,
                    "entity": "risk",
                    "op": "upsert",
                    "base_version": 1,
                    "record": {
                        "id": risk_id,
                        "title": "X",
                        "probability": 2,
                        "impact": 2,
                    },
                }
            ],
        }

        # First push.
        r = c.post(f"/projects/{pid}/sync/push", json=payload, headers=h)
        assert r.json()["accepted"] == 1

        # Second push with the same change_id.
        r = c.post(f"/projects/{pid}/sync/push", json=payload, headers=h)
        assert r.json()["duplicates"] == 1
        assert r.json()["accepted"] == 0
