"""Sync: version mismatch → conflict, not a silent overwrite."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def test_push_with_stale_base_version_returns_conflict(tmp_path, isolated_app_factory):
    """Sync push with a stale base_version returns a version_mismatch conflict"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'conflict.db'}")
    with TestClient(app) as c:
        r = c.post(
            "/register",
            json={"email": "u@test.com", "password": "Password123!"},
        )
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = c.post("/projects", json={"name": "P"}, headers=h)
        pid = r.json()["id"]

        r = c.post(
            f"/projects/{pid}/risks",
            json={
                "type": "risk",
                "title": "R",
                "probability": 3,
                "impact": 3,
            },
            headers=h,
        )
        risk_id = r.json()["id"]
        assert r.json()["version"] == 1

        # Push update claiming base_version=1 → succeeds, bumps to 2
        r = c.post(
            f"/projects/{pid}/sync/push",
            json={
                "project_id": pid,
                "changes": [
                    {
                        "change_id": str(uuid.uuid4()),
                        "entity": "risk",
                        "op": "upsert",
                        "base_version": 1,
                        "record": {
                            "id": risk_id,
                            "title": "V2",
                            "probability": 3,
                            "impact": 3,
                        },
                    }
                ],
            },
            headers=h,
        )
        assert r.json()["accepted"] == 1

        # Push another update still claiming base_version=1 → conflict
        r = c.post(
            f"/projects/{pid}/sync/push",
            json={
                "project_id": pid,
                "changes": [
                    {
                        "change_id": str(uuid.uuid4()),
                        "entity": "risk",
                        "op": "upsert",
                        "base_version": 1,
                        "record": {
                            "id": risk_id,
                            "title": "Stale",
                            "probability": 3,
                            "impact": 3,
                        },
                    }
                ],
            },
            headers=h,
        )
        result = r.json()
        assert result["accepted"] == 0
        assert len(result["conflicts"]) == 1
        assert result["conflicts"][0]["reason"] == "version_mismatch"
        assert result["conflicts"][0]["server_version"] == 2
